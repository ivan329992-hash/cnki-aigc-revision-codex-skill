#!/usr/bin/env python3
"""Read-only manuscript/report checks. This is not an AI detector."""

from __future__ import annotations

import argparse
from collections import Counter
import difflib
import hashlib
import json
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET
import zipfile

NS = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
W = '{' + NS['w'] + '}'
MAX_XML_BYTES = 20 * 1024 * 1024
INVISIBLE = re.compile('[\u200b\u200c\u200d\ufeff]')


def digest(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest() if hasattr(hashlib, 'file_digest') else hashlib.sha256(stream.read()).hexdigest()


def fold(text: str) -> str:
    # A deliberately lossy lookup key, never proof of byte identity.
    return re.sub(r'[\s\u201c\u201d"\u2018\u2019]', '', text)


def text_of(node: ET.Element) -> str:
    return ''.join(el.text or '' for el in node.iter(W + 't'))


def read_docx(path: Path) -> dict:
    with zipfile.ZipFile(path) as package:
        info = package.getinfo('word/document.xml')
        if info.file_size > MAX_XML_BYTES:
            raise ValueError('Document XML exceeds the supported size limit.')
        root = ET.fromstring(package.read(info))
        if any(root.find('.//w:' + tag, NS) is not None for tag in ('ins', 'del', 'moveFrom', 'moveTo')):
            raise ValueError('Tracked changes found; confirm a clean comparison copy first.')
        body = root.find('w:body', NS)
        if body is None:
            raise ValueError('Document body not found.')
        paragraphs, tables, ordered = [], [], []
        for child in body:
            if child.tag == W + 'p':
                value = text_of(child)
                paragraphs.append(value)
                ordered.append(value)
            elif child.tag == W + 'tbl':
                rows = [[text_of(cell) for cell in row.findall('w:tc', NS)]
                        for row in child.findall('w:tr', NS)]
                tables.append(rows)
                ordered.extend('\t'.join(row) for row in rows)
        refs_at = next((i for i, p in enumerate(paragraphs)
                        if p.strip().rstrip(':：').casefold() in ('参考文献', 'references')), None)
        warnings = []
        if root.find('.//w:txbxContent', NS) is not None:
            warnings.append('Text boxes need manual reading-order review.')
        if root.find('.//w:sdt', NS) is not None:
            warnings.append('Content-control text may be excluded; manually inspect the full document.')
        if 'word/footnotes.xml' in package.namelist():
            warnings.append('Footnote content is not included in paragraph matching.')
        if root.find('.//w:tbl//w:tbl', NS) is not None:
            warnings.append('Nested tables need manual review.')
        package_hashes = {name: hashlib.sha256(package.read(name)).hexdigest()
                          for name in package.namelist() if not name.endswith('/')}
    all_text = '\n'.join(ordered)
    return {'path': str(path.resolve()), 'sha256': digest(path),
            'paragraphs': paragraphs, 'tables': tables,
            'reference_heading_index': refs_at,
            'references': paragraphs[refs_at + 1:] if refs_at is not None else None,
            'invisible_character_count': len(INVISIBLE.findall(all_text)),
            'warnings': warnings, 'package_hashes': package_hashes}


def primary_metrics(first_page: str) -> dict:
    # Exclude front/middle/back-region metrics; those repeat the same labels.
    overall = first_page.split('全文检测结果', 1)[-1]
    overall = re.split(r'AIGC\s*片段分布图|前部\s*20\s*%|片段指标列表', overall, maxsplit=1)[0]
    values = {float(v) for v in re.findall(r'AI特征值\s*[:：]\s*(\d+(?:\.\d+)?)\s*%', overall)}
    def count_after(label):
        found = re.search(label + r'\s*[:：]\s*([0-9][0-9,， \u00a0\u202f]*)', overall)
        if not found:
            return None
        token = found[1].strip().replace('，', ',').replace('\u00a0', ' ').replace('\u202f', ' ')
        if not re.fullmatch(r'\d+|\d{1,3}(?:,\d{3})+|\d{1,3}(?: \d{3})+', token):
            return None
        return int(token.replace(',', '').replace(' ', ''))

    chars, total = count_after('AI特征字符数'), count_after('总字符数')
    result = {'overall_percent': next(iter(values)) if len(values) == 1 else None,
              'feature_characters': chars, 'total_characters': total,
              'status': 'parsed' if len(values) == 1 and chars is not None and total is not None else 'manual_review_required'}
    if len(values) > 1:
        result['status'] = 'ambiguous_overall_values'
    if result['overall_percent'] is not None and not 0 <= result['overall_percent'] <= 100:
        result['status'] = 'invalid_overall_value'
    if chars is not None and total is not None:
        count, size = chars, total
        if size <= 0 or count > size:
            result['status'] = 'invalid_character_counts'
        elif result['overall_percent'] is not None:
            result['ratio_consistent_with_rounding'] = abs(100 * count / size - result['overall_percent']) <= 0.15
            if not result['ratio_consistent_with_rounding']:
                result['status'] = 'inconsistent_metric_counts'
    return result


def read_report(path: Path, paragraphs: list[str], tables: list | None = None) -> dict:
    try:
        import fitz
    except ImportError as exc:
        raise ValueError('PDF inspection requires optional PyMuPDF; Word comparison does not.') from exc
    with fitz.open(path) as report:
        if not len(report):
            raise ValueError('PDF has no pages.')
        metrics = primary_metrics(report[0].get_text(sort=True))
        body_parts, red_mask = [], []
        for page in list(report)[1:]:
            for block in page.get_text('dict')['blocks']:
                for line in block.get('lines', []):
                    for span in line['spans']:
                        value = span['text'].strip()
                        if value in ('https://cx.cnki.net', '知网个人AIGC检测服务', 'cx.cnki.net'):
                            continue
                        if re.fullmatch(r'—\s*\d+\s*—|\d+(?:\.\d+)?%\(\d+\)', value):
                            continue
                        normalized = fold(value)
                        body_parts.append(normalized)
                        color = span.get('color', 0)
                        r, g, b = (color >> 16) & 255, (color >> 8) & 255, color & 255
                        red_mask.extend([r > 180 and g < 90 and b < 90] * len(normalized))
        body = ''.join(body_parts)
    matches, cursor = [], 0
    for i, text in enumerate(paragraphs):
        normalized = fold(text)
        if not normalized:
            continue
        at = body.find(normalized, cursor)
        matches.append({'paragraph': i, 'normalized_match': at >= 0,
                        'font_red_characters_heuristic': sum(red_mask[at:at + len(normalized)]) if at >= 0 else None})
        if at >= 0:
            cursor = at + len(normalized)
    table_matches, table_cursor = [], 0
    for ti, table in enumerate(tables or []):
        for ri, row in enumerate(table):
            for ci, cell in enumerate(row):
                normalized = fold(cell)
                if not normalized:
                    continue
                at = body.find(normalized, table_cursor)
                table_matches.append({'table': ti, 'row': ri, 'column': ci, 'normalized_match': at >= 0})
                if at >= 0:
                    table_cursor = at + len(normalized)
    return {'path': str(path.resolve()), 'sha256': digest(path), 'metrics': metrics,
            'matching_method': 'whitespace_quote_normalized_lookup_not_identity',
            'paragraph_matches': matches,
            'matched_paragraphs': sum(m['normalized_match'] for m in matches),
            'checked_paragraphs': len(matches),
            'table_cell_matches': table_matches,
            'checked_table_cells': len(table_matches),
            'matched_table_cells': sum(m['normalized_match'] for m in table_matches),
            'warnings': ['Color counts are not official feature-character counts.',
                         'Background highlights, scanned PDFs, sidebars and unusual ordering require visual review.',
                         'The first PDF page is used for metrics and excluded from body lookup.',
                         'Short cell values and merged tables require manual context verification.',
                         'Unmarked text is not proof of human authorship.']}


def numeric_tokens(text: str) -> Counter:
    return Counter(re.findall(r'[-+]?\d+(?:\.\d+)?[%％]?', text))


def citation_slots(text: str) -> list[str]:
    return re.findall(r'\[[\d,;\s\-–]+\]', text)


def compare_documents(base: dict, revised: dict) -> dict:
    a, b = base['paragraphs'], revised['paragraphs']
    blocks = []
    unchanged = 0
    for tag, a0, a1, b0, b1 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if tag == 'equal':
            unchanged += a1 - a0
            continue
        old, new = '\n'.join(a[a0:a1]), '\n'.join(b[b0:b1])
        blocks.append({'operation': tag, 'base_indices': list(range(a0, a1)),
                       'revised_indices': list(range(b0, b1)),
                       'before': a[a0:a1], 'after': b[b0:b1],
                       'numeric_token_multiset_equal': numeric_tokens(old) == numeric_tokens(new),
                       'citation_slots_equal': citation_slots(old) == citation_slots(new)})
    table_changes = []
    for i in range(max(len(base['tables']), len(revised['tables']))):
        old = base['tables'][i] if i < len(base['tables']) else None
        new = revised['tables'][i] if i < len(revised['tables']) else None
        if old != new:
            table_changes.append({'table': i, 'before': old, 'after': new})
    keys = set(base['package_hashes']) | set(revised['package_hashes'])
    refs_equal = base['references'] == revised['references']
    if base['references'] is None and revised['references'] is None:
        refs_equal = None
    return {'base': {'path': base['path'], 'sha256': base['sha256']},
            'revised': {'path': revised['path'], 'sha256': revised['sha256']},
            'changed_blocks': blocks, 'unchanged_paragraphs': unchanged,
            'table_text_changes': table_changes, 'reference_text_unchanged': refs_equal,
            'changed_package_parts': sorted(k for k in keys if base['package_hashes'].get(k) != revised['package_hashes'].get(k)),
            'invisible_character_counts': {'base': base['invisible_character_count'], 'revised': revised['invisible_character_count']},
            'warnings': base['warnings'] + revised['warnings'] + ['Equal numeric tokens do not prove equal units, scope, meaning or citation support.'],
            'detector_score_estimate': None}


def save_local(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    inspect = sub.add_parser('inspect')
    inspect.add_argument('--docx', type=Path, required=True)
    inspect.add_argument('--report', type=Path)
    inspect.add_argument('--out', type=Path, required=True)
    compare = sub.add_parser('compare')
    compare.add_argument('--base', type=Path, required=True)
    compare.add_argument('--revised', type=Path, required=True)
    compare.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == 'inspect':
            document = read_docx(args.docx)
            payload = {'document': document, 'detector_score_estimate': None}
            if args.report:
                end = document['reference_heading_index']
                payload['report'] = read_report(args.report, document['paragraphs'][:end], document['tables'])
        else:
            payload = compare_documents(read_docx(args.base), read_docx(args.revised))
        save_local(args.out, payload)
    except (OSError, ValueError, KeyError, RuntimeError, zipfile.BadZipFile, ET.ParseError) as exc:
        print(f'Audit stopped: {exc}', file=sys.stderr)
        return 2
    print('Wrote private local audit; no AI detection or network request was performed.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'skills/cnki-aigc-revision/scripts/audit_inputs.py'
SPEC = importlib.util.spec_from_file_location('audit_inputs', SCRIPT)
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


def make_docx(path, paragraphs, rows=None, tracked=False):
    root = ET.Element(audit.W + 'document')
    body = ET.SubElement(root, audit.W + 'body')
    for text in paragraphs:
        p = ET.SubElement(body, audit.W + 'p')
        parent = ET.SubElement(p, audit.W + 'ins') if tracked else p
        run = ET.SubElement(parent, audit.W + 'r')
        ET.SubElement(run, audit.W + 't').text = text
    if rows:
        table = ET.SubElement(body, audit.W + 'tbl')
        for row in rows:
            tr = ET.SubElement(table, audit.W + 'tr')
            for value in row:
                cell = ET.SubElement(tr, audit.W + 'tc')
                p = ET.SubElement(cell, audit.W + 'p')
                run = ET.SubElement(p, audit.W + 'r')
                ET.SubElement(run, audit.W + 't').text = value
    with zipfile.ZipFile(path, 'w') as package:
        package.writestr('word/document.xml', ET.tostring(root, encoding='utf-8'))


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.work = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def docs(self, old, new, old_rows=None, new_rows=None):
        a, b = self.work / 'a.docx', self.work / 'b.docx'
        make_docx(a, old, old_rows)
        make_docx(b, new, new_rows)
        return audit.read_docx(a), audit.read_docx(b)

    def test_reads_text_table_reference_and_hash(self):
        a, _ = self.docs(['标题', '24份[1]', '参考文献', '[1] 合成文献'], ['x'], [['资源', '数量']])
        self.assertEqual(a['references'], ['[1] 合成文献'])
        self.assertEqual(a['tables'], [[['资源', '数量']]])
        self.assertEqual(len(a['sha256']), 64)

    def test_paraphrase_preserves_numbers_and_citations(self):
        a, b = self.docs(['共24份，其中16份基础和8份补充[1]。'], ['16份基础、8份补充，合计24份[1]。'])
        result = audit.compare_documents(a, b)
        self.assertTrue(result['changed_blocks'][0]['numeric_token_multiset_equal'])
        self.assertTrue(result['changed_blocks'][0]['citation_slots_equal'])
        self.assertIsNone(result['detector_score_estimate'])

    def test_changed_number_and_reference_are_flagged(self):
        a, b = self.docs(['24份[1]'], ['25份[2]'])
        block = audit.compare_documents(a, b)['changed_blocks'][0]
        self.assertFalse(block['numeric_token_multiset_equal'])
        self.assertFalse(block['citation_slots_equal'])

    def test_insert_delete_are_not_position_zipped(self):
        a, b = self.docs(['甲', '乙', '丙'], ['新段', '甲', '丙'])
        result = audit.compare_documents(a, b)
        self.assertEqual(result['unchanged_paragraphs'], 2)
        self.assertEqual({x['operation'] for x in result['changed_blocks']}, {'insert', 'delete'})

    def test_table_and_reference_changes_are_reported(self):
        a, b = self.docs(['参考文献', '[1] 甲'], ['参考文献', '[1] 乙'], [['8']], [['9']])
        result = audit.compare_documents(a, b)
        self.assertFalse(result['reference_text_unchanged'])
        self.assertEqual(len(result['table_text_changes']), 1)

    def test_missing_reference_section_is_not_certified(self):
        a, b = self.docs(['甲'], ['甲'])
        self.assertIsNone(audit.compare_documents(a, b)['reference_text_unchanged'])

    def test_tracked_changes_refused(self):
        p = self.work / 'tracked.docx'
        make_docx(p, ['待确认'], tracked=True)
        with self.assertRaisesRegex(ValueError, 'Tracked changes'):
            audit.read_docx(p)

    def test_invisible_character_is_flagged(self):
        a, _ = self.docs(['普通\u200b文字'], ['普通文字'])
        self.assertEqual(a['invisible_character_count'], 1)

    def test_headline_is_not_fragment_or_suspicious_value(self):
        text = 'AI特征值：12.5%\nAI特征字符数：125\n总字符数：1000\n片段1 疑似 7.3%'
        result = audit.primary_metrics(text)
        self.assertEqual(result['overall_percent'], 12.5)
        self.assertEqual(result['status'], 'parsed')

    def test_inconsistent_or_ambiguous_metrics_require_review(self):
        self.assertEqual(audit.primary_metrics('AI特征值：88%\nAI特征字符数：10\n总字符数：1000')['status'], 'inconsistent_metric_counts')
        self.assertEqual(audit.primary_metrics('AI特征值：12%\nAI特征值：80%')['status'], 'ambiguous_overall_values')
        self.assertIsNone(audit.primary_metrics('片段1 9%')['overall_percent'])

    def test_regional_metrics_are_not_overall_metrics(self):
        text = '全文检测结果\nAI特征值：12.5%\nAI特征字符数：125\n总字符数：1000\nAIGC片段分布图\n前部20%\nAI特征值：75.2%\n中部60%\nAI特征值：0.0%'
        result = audit.primary_metrics(text)
        self.assertEqual(result['overall_percent'], 12.5)
        self.assertEqual(result['status'], 'parsed')

    def test_zero_denominator_is_invalid(self):
        self.assertEqual(audit.primary_metrics('AI特征值：0%\nAI特征字符数：0\n总字符数：0')['status'], 'invalid_character_counts')

    def test_grouped_counts_are_not_truncated(self):
        result = audit.primary_metrics('AI特征值：50%\nAI特征字符数：1,000\n总字符数：2,000')
        self.assertEqual((result['feature_characters'], result['total_characters']), (1000, 2000))
        self.assertEqual(result['status'], 'parsed')
        result = audit.primary_metrics('AI特征值：50%\nAI特征字符数：1,00\n总字符数：2,00')
        self.assertNotEqual(result['status'], 'parsed')

    def test_content_controls_are_not_silently_ignored(self):
        p = self.work / 'controls.docx'
        xml = f'<w:document xmlns:w="{audit.NS["w"]}"><w:body><w:sdt><w:sdtContent><w:p><w:r><w:t>合成内容</w:t></w:r></w:p></w:sdtContent></w:sdt></w:body></w:document>'
        with zipfile.ZipFile(p, 'w') as package:
            package.writestr('word/document.xml', xml)
        self.assertTrue(audit.read_docx(p)['warnings'])

    def test_existing_output_is_not_overwritten(self):
        out = self.work / 'out.json'
        out.write_text('original', encoding='utf-8')
        with self.assertRaises(FileExistsError):
            audit.save_local(out, {'x': 1})
        self.assertEqual(out.read_text(), 'original')

    def test_cli_does_not_modify_inputs(self):
        source = self.work / 'draft.docx'
        make_docx(source, ['合成文本'])
        before = audit.digest(source)
        output = self.work / 'audit.json'
        run = subprocess.run([sys.executable, str(SCRIPT), 'inspect', '--docx', str(source), '--out', str(output)], capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(audit.digest(source), before)
        self.assertIsNone(json.loads(output.read_text(encoding='utf-8'))['detector_score_estimate'])

    def test_pdf_lookup_with_synthetic_report(self):
        try:
            import fitz
        except ImportError:
            self.skipTest('Optional PyMuPDF is unavailable')
        report = fitz.open()
        first = report.new_page()
        first.insert_text((40, 60), 'AI特征值：12.5%\nAI特征字符数：125\n总字符数：1000', fontname='china-s')
        body = report.new_page()
        body.insert_text((40, 60), '合成测试正文', fontname='china-s', color=(0.9, 0, 0))
        path = self.work / 'report.pdf'
        report.save(path)
        report.close()
        result = audit.read_report(path, ['合成测试正文', '不存在的段落'])
        self.assertEqual(result['metrics']['overall_percent'], 12.5)
        self.assertTrue(result['paragraph_matches'][0]['normalized_match'])
        self.assertGreater(result['paragraph_matches'][0]['font_red_characters_heuristic'], 0)
        self.assertFalse(result['paragraph_matches'][1]['normalized_match'])

    def test_repeated_text_and_table_mismatch(self):
        try:
            import fitz
        except ImportError:
            self.skipTest('Optional PyMuPDF is unavailable')
        pdf = fitz.open()
        pdf.new_page().insert_text((40, 60), 'AI特征值：10%\nAI特征字符数：10\n总字符数：100', fontname='china-s')
        page = pdf.new_page()
        page.insert_text((40, 60), '重复段落', fontname='china-s')
        page.insert_text((40, 90), '重复段落', fontname='china-s', color=(0.9, 0, 0))
        page.insert_text((40, 120), '表中共有12份记录', fontname='china-s')
        path = self.work / 'repeated.pdf'
        pdf.save(path)
        pdf.close()
        result = audit.read_report(path, ['重复段落', '重复段落'], [[['表中共有14份记录']]])
        self.assertEqual(result['paragraph_matches'][0]['font_red_characters_heuristic'], 0)
        self.assertGreater(result['paragraph_matches'][1]['font_red_characters_heuristic'], 0)
        self.assertEqual(result['checked_table_cells'], 1)
        self.assertEqual(result['matched_table_cells'], 0)


if __name__ == '__main__':
    unittest.main()

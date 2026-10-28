"""Notion / 印象笔记导入的测试（不联网）。"""

from __future__ import annotations

import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pokercoach.importers import evernote, notion

ENEX = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE en-export SYSTEM "http://xml.evernote.com/pub/evernote-export3.dtd">
<en-export export-date="20240101T000000Z" application="Evernote">
  <note>
    <title>翻前 3bet 笔记</title>
    <content><![CDATA[<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE en-note SYSTEM "http://xml.evernote.com/pub/enml2.dtd">
<en-note><div>BTN vs CO 的 3bet 要极化。</div><div><br/></div>
<div>价值端：QQ+、AK。</div><ul><li>A5s 做诈唬</li><li>K9s 也可以</li></ul></en-note>]]></content>
    <tag>翻前</tag>
    <tag>3bet</tag>
    <created>20240101T120000Z</created>
    <guid>aaaa1111-bbbb-cccc-dddd-eeeeffff0000</guid>
  </note>
  <note>
    <title>空笔记</title>
    <content><![CDATA[<en-note><div><br/></div></en-note>]]></content>
    <guid>bbbb2222-cccc-dddd-eeee-ffff00001111</guid>
  </note>
</en-export>
"""


class TestEvernote(unittest.TestCase):
    def test_enml_to_text(self):
        html = "<en-note><div>第一段</div><div>第二段</div><ul><li>要点一</li></ul></en-note>"
        text = evernote.enml_to_text(html)
        self.assertIn("第一段", text)
        self.assertIn("- 要点一", text)
        self.assertNotIn("<", text)

    def test_parse_enex(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "notes.enex"
            p.write_text(ENEX, encoding="utf-8")
            notes = evernote.parse_enex(p)
            self.assertEqual(len(notes), 2)
            self.assertEqual(notes[0]["title"], "翻前 3bet 笔记")
            self.assertIn("极化", notes[0]["body"])
            self.assertEqual(notes[0]["tags"], ["翻前", "3bet"])

    def test_import_enex_writes_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "notes.enex"
            p.write_text(ENEX, encoding="utf-8")
            out = Path(tmp) / "out"
            stats = evernote.import_enex(p, out, log=lambda *_: None)
            self.assertEqual(stats["written"], 1)  # 空笔记跳过
            files = list(out.glob("*.md"))
            self.assertEqual(len(files), 1)
            self.assertTrue(files[0].read_text(encoding="utf-8").startswith("# 翻前 3bet 笔记"))


class TestNotionRender(unittest.TestCase):
    def test_blocks_to_markdown(self):
        blocks = [
            {"type": "heading_2", "heading_2": {"rich_text": [{"plain_text": "3bet 范围", "type": "text"}]}},
            {"type": "paragraph", "paragraph": {"rich_text": [
                {"plain_text": "BTN 用 ", "type": "text"},
                {"plain_text": "QQ+", "type": "text", "annotations": {"bold": True}},
            ]}},
            {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"plain_text": "A5s 诈唬", "type": "text"}]}},
            {"type": "to_do", "to_do": {"checked": True, "rich_text": [{"plain_text": "看完第四节", "type": "text"}]}},
            {"type": "code", "code": {"language": "python", "rich_text": [{"plain_text": "print(1)", "type": "text"}]}},
            {"type": "divider", "divider": {}},
        ]
        md = notion.blocks_to_markdown(blocks)
        self.assertIn("## 3bet 范围", md)
        self.assertIn("**QQ+**", md)
        self.assertIn("- A5s 诈唬", md)
        self.assertIn("- [x] 看完第四节", md)
        self.assertIn("```python", md)

    def test_title_from_properties(self):
        page = {"properties": {"Name": {"type": "title", "title": [{"plain_text": "河牌抓诈唬"}]}}}
        client = notion.NotionClient("fake")
        self.assertEqual(client.page_title(page), "河牌抓诈唬")


class TestNotionZip(unittest.TestCase):
    def test_import_zip(self):
        with tempfile.TemporaryDirectory() as tmp:
            zp = Path(tmp) / "export.zip"
            with zipfile.ZipFile(zp, "w") as zf:
                zf.writestr(
                    "扑克课程/翻前 3bet 策略 3f2a1b4c5d6e7f8091a2b3c4d5e6f708.md",
                    "# 翻前 3bet 策略\n\nBTN vs CO 要极化。\n",
                )
                zf.writestr("扑克课程/河牌 抓诈唬 9a8b7c6d5e4f30211f2e3d4c5b6a7089.md", "# 河牌 抓诈唬\n\n看阻断牌。\n")
            out = Path(tmp) / "out"
            stats = notion.import_notion_zip(zp, out, log=lambda *_: None)
            self.assertEqual(stats["written"], 2)
            names = sorted(f.name for f in out.glob("*.md"))
            self.assertTrue(any(n.startswith("翻前 3bet 策略") for n in names))
            self.assertFalse(any("3f2a1b4c5d6e7f80" in n for n in names), "hash 后缀应该被去掉")


if __name__ == "__main__":
    unittest.main()

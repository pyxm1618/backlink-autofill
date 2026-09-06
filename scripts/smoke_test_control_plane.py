#!/usr/bin/env python3
"""Read-only smoke test verifying the Backlink Autofill runtime control plane."""

import os
import json
import gspread
from pathlib import Path

os.environ['http_proxy'] = 'http://127.0.0.1:15236'
os.environ['https_proxy'] = 'http://127.0.0.1:15236'

CREDENTIALS_FILE = os.path.expanduser('~/.config/seo-sheets/service-account.json')
CONFIG_PATH = Path.home() / '.backlink-autofill' / 'control-plane.json'


def main():
    print("=== Step 1: Read and verify local control-plane.json ===")
    assert CONFIG_PATH.exists(), f"Config file not found at {CONFIG_PATH}"
    config = json.loads(CONFIG_PATH.read_text(encoding='utf-8'))
    print(f"Loaded config: {config}")

    spreadsheet_id = config.get("spreadsheet_id")
    master_tab_name = config.get("master_sheet")
    project_tab_name = config.get("project_sheet")

    assert spreadsheet_id, "Missing spreadsheet_id in config"
    assert master_tab_name == "外链总表", f"Unexpected master_sheet: {master_tab_name}"
    assert project_tab_name == "外链管理", f"Unexpected project_sheet: {project_tab_name}"
    print("✓ Local configuration verified")

    print("\n=== Step 2: Connect to Google Sheet and check tabs ===")
    gc = gspread.service_account(filename=CREDENTIALS_FILE)
    sh = gc.open_by_key(spreadsheet_id)
    titles = [ws.title for ws in sh.worksheets()]
    print(f"Spreadsheet title: {sh.title!r}")
    print(f"Worksheets present: {titles}")

    assert master_tab_name in titles, f"Master tab {master_tab_name!r} not found in spreadsheet"
    assert project_tab_name in titles, f"Project tab {project_tab_name!r} not found in spreadsheet"
    print(f"✓ Successfully verified tabs: {master_tab_name} AND {project_tab_name}")

    print("\n=== Step 3: Verify tab headers ===")
    master_ws = sh.worksheet(master_tab_name)
    master_header = master_ws.row_values(1)
    print(f"Master header: {master_header}")
    expected_master_header = [
        "外链ID", "平台域名", "提交入口", "发现来源", "发现时间",
        "基础状态", "基础排除原因", "实测免费", "实测需登录", "实测登录方式",
        "实测限制", "实测链接属性", "最后验证时间", "平台备注"
    ]
    assert master_header == expected_master_header, f"Master header mismatch: {master_header}"
    print("✓ Master header strictly matches contract")

    project_ws = sh.worksheet(project_tab_name)
    project_header = project_ws.row_values(1)
    print(f"Project header: {project_header}")
    expected_project_header = [
        "项目ID", "外链ID", "外链域名", "状态", "尝试次数",
        "最近操作时间", "目标URL", "结果链接", "原因/备注", "证据摘要"
    ]
    assert project_header == expected_project_header, f"Project header mismatch: {project_header}"
    print("✓ Project header strictly matches contract (including 外链域名)")

    print("\n=== Step 4: Verify Tab Visibility ===")
    meta = sh.fetch_sheet_metadata()
    for s in meta.get("sheets", []):
        p = s["properties"]
        t = p["title"]
        hidden = p.get("hidden", False)
        if t == "外链管理":
            assert not hidden, "外链管理 tab must be visible"
            print(f"  Visible Tab: {t}")
        else:
            assert hidden, f"Tab {t} should be hidden"
            print(f"  Hidden Tab: {t}")
    print("✓ Tab visibility strictly verified: only 外链管理 is visible")

    print("\n=== Step 5: Read-only queue query and join simulation ===")
    project_rows = project_ws.get_all_values()
    quick_iching_rows = [
        (idx + 1, r) for idx, r in enumerate(project_rows[1:])
        if r and len(r) > 3 and r[0] == "quick-iching"
    ]
    print(f"Total quick-iching rows in {project_tab_name}: {len(quick_iching_rows)}")
    assert len(quick_iching_rows) == 36, f"Expected 36 quick-iching rows, got {len(quick_iching_rows)}"

    pending_rows = [(row_num, r) for row_num, r in quick_iching_rows if r[3] == "待提交"]
    print(f"Pending (待提交) rows: {len(pending_rows)}")

    # Sample join with 外链总表
    if pending_rows:
        sample_row_num, sample_r = pending_rows[0]
        backlink_id = sample_r[1]
        print(f"Sample pending task: Row {sample_row_num}, backlink_id={backlink_id}")

        # Search master tab for this backlink_id
        cell = master_ws.find(backlink_id, in_column=1)
        assert cell is not None, f"Could not find backlink_id {backlink_id} in master tab"
        master_data_row = master_ws.row_values(cell.row)
        print(f"Found master row {cell.row}: {master_data_row[:6]}")
        print(f"  平台域名: {master_data_row[1]}")
        print(f"  提交入口: {master_data_row[2]}")
        print(f"  基础状态: {master_data_row[5]}")
        print("✓ Join via 外链ID verified successfully")

    print("\n=== ALL READ-ONLY SMOKE TESTS PASSED ===")


if __name__ == "__main__":
    main()

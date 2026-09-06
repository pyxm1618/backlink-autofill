#!/usr/bin/env python3
"""Idempotent Google Sheet UX Migration Script for Backlink Autofill.

Enforces:
1. Rename '项目外链管理' -> '外链管理'
2. Update header: '平台域名' -> '外链域名'
3. Hide technical columns: 外链ID (B), 尝试次数 (E), 目标URL (G)
4. Freeze physical columns A:C (frozenColumnCount = 3, frozenRowCount = 1)
5. Adjust column widths and row wrapping
6. Idempotently hide non-daily tabs:
   - 外链总表
   - 黑名单视图
   - 外链总表_backup_20260906
   - 项目外链管理_backup_20260906
   Only '外链管理' remains visible.
7. Full row-by-row lossless data verification against pre-migration snapshot.
"""

import os
import json
import gspread

os.environ['http_proxy'] = 'http://127.0.0.1:15236'
os.environ['https_proxy'] = 'http://127.0.0.1:15236'

from pathlib import Path

CREDENTIALS_FILE = os.path.expanduser('~/.config/seo-sheets/service-account.json')
CONFIG_PATH = Path.home() / '.backlink-autofill' / 'control-plane.json'


def run_migration():
    if not CONFIG_PATH.exists():
        raise SystemExit(f"Control plane config not found at {CONFIG_PATH}")
    config = json.loads(CONFIG_PATH.read_text(encoding='utf-8'))
    spreadsheet_id = config.get("spreadsheet_id")
    if not spreadsheet_id:
        raise SystemExit("spreadsheet_id missing from control-plane.json")

    gc = gspread.service_account(filename=CREDENTIALS_FILE)
    sh = gc.open_by_key(spreadsheet_id)

    meta = sh.fetch_sheet_metadata()
    sheets = meta.get('sheets', [])
    sheet_by_id = {s['properties']['sheetId']: s['properties'] for s in sheets}
    sheet_by_title = {s['properties']['title']: s['properties'] for s in sheets}

    # 1. 查找项目执行表 (通过 sheetId 2139391078 或 title '项目外链管理'/'外链管理')
    target_sheet_id = 2139391078
    target_props = sheet_by_id.get(target_sheet_id)
    if not target_props:
        if '外链管理' in sheet_by_title:
            target_props = sheet_by_title['外链管理']
            target_sheet_id = target_props['sheetId']
        elif '项目外链管理' in sheet_by_title:
            target_props = sheet_by_title['项目外链管理']
            target_sheet_id = target_props['sheetId']
        else:
            raise RuntimeError("Could not find project management worksheet by ID or title")

    print(f"Target worksheet found: title={target_props['title']!r}, sheetId={target_sheet_id}")

    # 读取当前数据并保存快照
    ws = sh.get_worksheet_by_id(target_sheet_id)
    pre_data = ws.get_all_values()
    print(f"Pre-migration row count: {len(pre_data)}")
    header = pre_data[0] if pre_data else []
    print(f"Pre-migration header: {header}")

    # 构造 batchUpdate 请求列表
    requests = []

    # A. 确保目标工作表重命名为 '外链管理'，冻结前 3 列与前 1 行，且保持可见 (hidden=False)
    requests.append({
        "updateSheetProperties": {
            "properties": {
                "sheetId": target_sheet_id,
                "title": "外链管理",
                "hidden": False,
                "gridProperties": {
                    "frozenRowCount": 1,
                    "frozenColumnCount": 3,
                },
            },
            "fields": "title,hidden,gridProperties.frozenRowCount,gridProperties.frozenColumnCount",
        }
    })

    # B. 隐藏其余 Tab (幂等执行)
    hide_targets = ["外链总表", "黑名单视图", "外链总表_backup_20260906", "项目外链管理_backup_20260906"]
    for title in hide_targets:
        if title in sheet_by_title:
            s_props = sheet_by_title[title]
            s_id = s_props['sheetId']
            if not s_props.get('hidden', False):
                print(f"Hiding tab {title!r} (sheetId={s_id})")
                requests.append({
                    "updateSheetProperties": {
                        "properties": {
                            "sheetId": s_id,
                            "hidden": True,
                        },
                        "fields": "hidden",
                    }
                })
            else:
                print(f"Tab {title!r} is already hidden (idempotent)")

    # C. 隐藏技术列: 外链ID (B: 索引 1), 尝试次数 (E: 索引 4), 目标URL (G: 索引 6)
    hidden_cols = [(1, 2), (4, 5), (6, 7)]
    for start_idx, end_idx in hidden_cols:
        requests.append({
            "updateDimensionProperties": {
                "range": {
                    "sheetId": target_sheet_id,
                    "dimension": "COLUMNS",
                    "startIndex": start_idx,
                    "endIndex": end_idx,
                },
                "properties": {
                    "hiddenByUser": True,
                },
                "fields": "hiddenByUser",
            }
        })

    # D. 确保日常可见列显示 (A: 0-1, C: 2-3, D: 3-4, F: 5-6, H: 7-8, I: 8-9, J: 9-10)
    visible_cols = [(0, 1), (2, 4), (5, 6), (7, 10)]
    for start_idx, end_idx in visible_cols:
        requests.append({
            "updateDimensionProperties": {
                "range": {
                    "sheetId": target_sheet_id,
                    "dimension": "COLUMNS",
                    "startIndex": start_idx,
                    "endIndex": end_idx,
                },
                "properties": {
                    "hiddenByUser": False,
                },
                "fields": "hiddenByUser",
            }
        })

    # E. 设置列宽
    col_widths = {
        0: 120,  # 项目ID
        1: 100,  # 外链ID (隐藏)
        2: 180,  # 外链域名
        3: 100,  # 状态
        4: 80,   # 尝试次数 (隐藏)
        5: 160,  # 最近操作时间
        6: 150,  # 目标URL (隐藏)
        7: 250,  # 结果链接
        8: 300,  # 原因/备注
        9: 350,  # 证据摘要
    }
    for col_idx, width in col_widths.items():
        requests.append({
            "updateDimensionProperties": {
                "range": {
                    "sheetId": target_sheet_id,
                    "dimension": "COLUMNS",
                    "startIndex": col_idx,
                    "endIndex": col_idx + 1,
                },
                "properties": {
                    "pixelSize": width,
                },
                "fields": "pixelSize",
            }
        })

    # 执行 batch_update
    if requests:
        print(f"Executing batchUpdate with {len(requests)} mutations...")
        sh.batch_update({"requests": requests})
        print("batchUpdate successful.")

    # F. 更新表头第 3 列 (C1: '平台域名' -> '外链域名')
    target_ws = sh.get_worksheet_by_id(target_sheet_id)
    cur_header = target_ws.row_values(1)
    if len(cur_header) >= 3 and cur_header[2] != '外链域名':
        print(f"Updating cell C1 from {cur_header[2]!r} to '外链域名'...")
        target_ws.update_acell('C1', '外链域名')
        print("C1 updated.")
    else:
        print("C1 is already '外链域名' (idempotent)")

    # 4. 读取修改后的状态与数据验证
    post_meta = sh.fetch_sheet_metadata()
    print("\n=== Post-migration Worksheet State ===")
    for s in post_meta.get('sheets', []):
        p = s['properties']
        print(f"  Title: {p['title']}, Hidden: {p.get('hidden', False)}, SheetId: {p['sheetId']}")

    post_ws = sh.worksheet('外链管理')
    post_data = post_ws.get_all_values()
    print(f"\nPost-migration row count: {len(post_data)}")
    print(f"Post-migration header: {post_data[0] if post_data else []}")

    # 5. 全字段数据对比验证
    print("\n=== Strict Lossless Data Verification ===")
    pre_rows = [r for r in pre_data[1:] if any(c.strip() for c in r)]
    post_rows = [r for r in post_data[1:] if any(c.strip() for c in r)]

    assert len(pre_rows) == len(post_rows) == 36, f"Row count mismatch: pre={len(pre_rows)}, post={len(post_rows)}"
    print("✓ Row count strictly preserved: 36 rows")

    # 逐条对比字段 (以 项目ID + 外链ID 为稳定主键)
    # pre row schema: 项目ID(0), 外链ID(1), 平台域名(2), 状态(3), 尝试次数(4), 最近操作时间(5), 目标URL(6), 结果链接(7), 原因/备注(8), 证据摘要(9)
    # post row schema: 项目ID(0), 外链ID(1), 外链域名(2), 状态(3), 尝试次数(4), 最近操作时间(5), 目标URL(6), 结果链接(7), 原因/备注(8), 证据摘要(9)
    mismatches = []
    for i, (pre_r, post_r) in enumerate(zip(pre_rows, post_rows)):
        key_pre = (pre_r[0], pre_r[1])
        key_post = (post_r[0], post_r[1])
        if key_pre != key_post:
            mismatches.append(f"Row {i+2} key mismatch: pre={key_pre}, post={key_post}")
            continue

        # 对比除域名列名差异外的每一个具体字段值
        # 项目ID
        if pre_r[0] != post_r[0]:
            mismatches.append(f"Row {i+2} 项目ID mismatch: {pre_r[0]} != {post_r[0]}")
        # 外链ID
        if pre_r[1] != post_r[1]:
            mismatches.append(f"Row {i+2} 外链ID mismatch: {pre_r[1]} != {post_r[1]}")
        # 外链域名值与原平台域名值必须相等
        if pre_r[2] != post_r[2]:
            mismatches.append(f"Row {i+2} 域名值 mismatch: {pre_r[2]} != {post_r[2]}")
        # 状态
        if pre_r[3] != post_r[3]:
            mismatches.append(f"Row {i+2} 状态 mismatch: {pre_r[3]} != {post_r[3]}")
        # 尝试次数
        if pre_r[4] != post_r[4]:
            mismatches.append(f"Row {i+2} 尝试次数 mismatch: {pre_r[4]} != {post_r[4]}")
        # 最近操作时间
        if pre_r[5] != post_r[5]:
            mismatches.append(f"Row {i+2} 最近操作时间 mismatch: {pre_r[5]} != {post_r[5]}")
        # 目标URL
        if pre_r[6] != post_r[6]:
            mismatches.append(f"Row {i+2} 目标URL mismatch: {pre_r[6]} != {post_r[6]}")
        # 结果链接 (绝不能被虚构或修改)
        if pre_r[7] != post_r[7]:
            mismatches.append(f"Row {i+2} 结果链接 mismatch: {pre_r[7]} != {post_r[7]}")
        # 原因/备注
        if pre_r[8] != post_r[8]:
            mismatches.append(f"Row {i+2} 原因/备注 mismatch: {pre_r[8]} != {post_r[8]}")
        # 证据摘要
        if pre_r[9] != post_r[9]:
            mismatches.append(f"Row {i+2} 证据摘要 mismatch: {pre_r[9]} != {post_r[9]}")

    if mismatches:
        for m in mismatches:
            print(f"  MISMATCH: {m}")
        raise AssertionError(f"Total {len(mismatches)} mismatches found in 36 data rows!")

    print("✓ All 36 data rows verified 100% identical in every single field!")
    print("✓ No synthetic result URLs introduced.")
    print("✓ Migration completed successfully.")


if __name__ == "__main__":
    run_migration()

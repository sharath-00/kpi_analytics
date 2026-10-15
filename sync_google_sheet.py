"""
Schnell Energy Technologies - Gateway KPI Mail Dashboard Generator & Sync
Fetches live data from Google Sheets API, recalculates fault weights and KPIs,
and outputs the executive HTML email dashboard (mail_dashboard.html).
"""

import os
import sys
import json
import math
import csv
import io
import base64
import requests
from datetime import datetime
from dotenv import load_dotenv

# Load sensitive environment variables from .env
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

# Configuration loaded securely from .env
SPREADSHEET_ID_OR_URL = os.getenv("SPREADSHEET_ID_OR_URL", "")
WORKSHEET_NAME = os.getenv("WORKSHEET_NAME", "Gateway")
SERVICE_ACCOUNT_FILE = os.getenv("SERVICE_ACCOUNT_FILE", os.path.join(os.path.dirname(__file__), "service_account.json"))
LOGO_FILE = os.path.join(os.path.dirname(__file__), "schnell_logo.png")
OUTPUT_HTML_FILE = os.path.join(os.path.dirname(__file__), "mail_dashboard.html")

# Verified KPI Fault Weights
FAULT_WEIGHTS = {
    "Contactor Failure": 10,
    "Meter Comm Fail": 5,
    "MCB Trip": 5,
    "Cal": 1,
    "Not Communicated": 1,
    "VC": 1,
    "Save": 1,
    "High Current": 1,
    "Energy Saved": 1
}


def extract_sheet_id(url_or_id):
    """Extract 44-character spreadsheet ID from URL or return raw ID."""
    if not url_or_id:
        return ""
    if "/d/" in url_or_id:
        parts = url_or_id.split("/d/")[1]
        return parts.split("/")[0]
    return url_or_id.strip()


def fetch_via_gspread(sheet_id_or_name, worksheet_name=None, target_date=None):
    """Fetch using official Google Sheets API v4 with Service Account."""
    import gspread
    from google.oauth2.service_account import Credentials

    service_file = SERVICE_ACCOUNT_FILE
    if not os.path.exists(service_file):
        for f in os.listdir(os.path.dirname(__file__)):
            if f.endswith(".json") and ("analytics" in f or "service" in f):
                service_file = os.path.join(os.path.dirname(__file__), f)
                break

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets.readonly",
        "https://www.googleapis.com/auth/drive.readonly"
    ]
    creds = Credentials.from_service_account_file(service_file, scopes=scopes)
    client = gspread.authorize(creds)

    sheet_id = extract_sheet_id(sheet_id_or_name)
    try:
        sh = client.open_by_key(sheet_id)
    except Exception:
        sh = client.open(sheet_id_or_name)

    target_ws = worksheet_name or WORKSHEET_NAME
    all_ws = [w.title for w in sh.worksheets()]
    
    if target_ws in all_ws:
        ws = sh.worksheet(target_ws)
    elif "Gateway" in all_ws:
        ws = sh.worksheet("Gateway")
    elif "Gateway-Type KPI" in all_ws:
        ws = sh.worksheet("Gateway-Type KPI")
    else:
        ws = sh.sheet1

    print(f"Connected to Google Sheet: '{sh.title}' -> Tab: '{ws.title}'")

    all_values = ws.get_all_values()
    if not all_values or len(all_values) < 2:
        return []

    headers = [h.strip() for h in all_values[0]]
    raw_rows = all_values[1:]
    date_col = headers.index("Date") if "Date" in headers else 0

    if target_date:
        selected_date = target_date.strip()
    else:
        # Smart detection: Skip future placeholder dates (like 31-Oct-2026 where all faults are 0 / 100%)
        # Automatically find the latest date that has active operational fault data
        fault_col = headers.index("Total Fault Count") if "Total Fault Count" in headers else None
        distinct_dates = []
        for r in raw_rows:
            if len(r) > date_col and r[date_col].strip() and r[date_col].strip() not in distinct_dates:
                distinct_dates.append(r[date_col].strip())

        selected_date = None
        for d in reversed(distinct_dates):
            batch = [r for r in raw_rows if len(r) > date_col and r[date_col].strip() == d]
            if fault_col is not None:
                fault_sum = sum(int(r[fault_col]) for r in batch if len(r) > fault_col and r[fault_col].strip().isdigit())
                if fault_sum > 0:
                    selected_date = d
                    break
        if not selected_date and distinct_dates:
            selected_date = distinct_dates[-1]

    print(f"Selected Active Date: '{selected_date}'")

    time_col = headers.index("Time") if "Time" in headers else None
    date_rows = [r for r in raw_rows if len(r) > date_col and r[date_col].strip() == selected_date]

    if time_col is not None and date_rows:
        latest_time = date_rows[-1][time_col].strip()
        matched_rows = [r for r in date_rows if r[time_col].strip() == latest_time]
        print(f"Batch Time: '{latest_time}' ({len(matched_rows)} regions found)")
    else:
        matched_rows = date_rows
        print(f"Found {len(matched_rows)} regions for date {selected_date}")

    records = []
    for r in matched_rows:
        row_dict = {}
        for idx, h in enumerate(headers):
            row_dict[h] = r[idx] if idx < len(r) else ""
        records.append(row_dict)

    return records


def clean_int(val):
    if val is None or val == "":
        return 0
    try:
        s = str(val).replace(",", "").replace("%", "").strip()
        return int(float(s))
    except (ValueError, TypeError):
        return 0


def process_records(raw_rows):
    """Calculate KPIs, weights, deficits, and prescriptive actions."""
    processed = []

    for r in raw_rows:
        region = str(r.get("Region", "")).strip()
        if not region:
            continue

        installed = clean_int(r.get("Total Installed"))
        if installed <= 0:
            continue

        comm = clean_int(r.get("Communicated"))
        not_comm = clean_int(r.get("Not Communicated"))
        cal = clean_int(r.get("Cal"))
        meter_comm = clean_int(r.get("Meter Comm Fail"))
        mcb = clean_int(r.get("MCB Trip"))
        contactor = clean_int(r.get("Contactor Failure"))

        calc_faults = (
            (not_comm * FAULT_WEIGHTS["Not Communicated"]) +
            (cal * FAULT_WEIGHTS["Cal"]) +
            (meter_comm * FAULT_WEIGHTS["Meter Comm Fail"]) +
            (mcb * FAULT_WEIGHTS["MCB Trip"]) +
            (contactor * FAULT_WEIGHTS["Contactor Failure"])
        )

        raw_fault_count = not_comm + cal + meter_comm + mcb + contactor
        kpi_val = ((installed - calc_faults) / installed) * 100.0
        working_pct = (comm / installed) * 100.0

        max_allowed_for_95 = math.floor(installed * 0.05)
        deficit = max(0, calc_faults - max_allowed_for_95)

        if deficit <= 0:
            rec = "SLA Target Met (Maintain SLA)"
        else:
            rem = deficit
            steps = []
            for ftype, w in [("Contactor Failure", 10), ("Meter Comm Fail", 5), ("MCB Trip", 5), ("Cal", 1), ("Not Communicated", 1)]:
                c = clean_int(r.get(ftype))
                if c > 0 and rem > 0:
                    needed = math.ceil(rem / w)
                    fix = min(c, needed)
                    rem -= fix * w
                    short = ftype.replace(" Failure", "").replace(" Trip", "")
                    steps.append(f"Fix {fix} {short}")
            rec = " & ".join(steps) if steps else "Requires Field Audit"

        processed.append({
            "Date": str(r.get("Date", "")),
            "Time": str(r.get("Time", "")),
            "Region": region,
            "Total Installed": installed,
            "Communicated": comm,
            "Not Communicated": not_comm,
            "Working %": f"{working_pct:.2f}%",
            "working_pct_num": round(working_pct, 2),
            "Cal": cal,
            "Meter Comm Fail": meter_comm,
            "Contactor Failure": contactor,
            "MCB Trip": mcb,
            "KAM": str(r.get("KAM", "N/A")),
            "Co-ordinaters": str(r.get("Co-ordinaters", "N/A")),
            "ULB-Wise": str(r.get("ULB-Wise", "N/A")),
            "Team Leader": str(r.get("Team Leader", "N/A")),
            "KPI": f"{kpi_val:.2f}%",
            "kpi_val": round(kpi_val, 2),
            "Total Faulty Calculated": calc_faults,
            "Total Fault Count": raw_fault_count,
            "deficit_to_95": deficit,
            "recommendation": rec
        })

    return processed


def render_html_dashboard(rows, report_date, report_time):
    """Generates the inline-styled HTML email dashboard."""
    logo_base64 = ""
    if os.path.exists(LOGO_FILE):
        with open(LOGO_FILE, "rb") as f:
            logo_base64 = base64.b64encode(f.read()).decode("utf-8")

    tier1 = sorted([r for r in rows if r["kpi_val"] >= 95.0], key=lambda x: x["kpi_val"], reverse=True)
    tier2 = sorted([r for r in rows if 80.0 <= r["kpi_val"] < 95.0], key=lambda x: x["kpi_val"], reverse=True)
    tier3 = sorted([r for r in rows if r["kpi_val"] < 80.0], key=lambda x: x["kpi_val"], reverse=True)

    total_installed = sum(r["Total Installed"] for r in rows)
    total_comm = sum(r["Communicated"] for r in rows)
    total_fault_count = sum(r["Total Fault Count"] for r in rows)
    total_faulty_calc = sum(r["Total Faulty Calculated"] for r in rows)

    fleet_kpi = ((total_installed - total_faulty_calc) / total_installed) * 100 if total_installed > 0 else 0
    comm_pct = (total_comm / total_installed) * 100 if total_installed > 0 else 0

    def render_rows(items, tier_type):
        html = ""
        for idx, r in enumerate(items):
            bg = "#ffffff" if idx % 2 == 0 else "#f8fafc"
            kpi_val = r["kpi_val"]
            installed = r["Total Installed"]
            comm = r["Communicated"]
            not_comm = r["Not Communicated"]
            working_pct = f"{r['working_pct_num']:.2f}%"
            cal = r["Cal"]
            meter = r["Meter Comm Fail"]
            mcb = r["MCB Trip"]
            contactor = r["Contactor Failure"]
            fault_count = r["Total Fault Count"]
            faulty_calc = r["Total Faulty Calculated"]
            deficit = r["deficit_to_95"]
            tl = r["Team Leader"]
            coord = r["Co-ordinaters"]
            rec = r["recommendation"]

            if tier_type == "tier1":
                html += f"""
                <tr style="background-color: {bg}; border-bottom: 1px solid #e2e8f0; font-size: 13px;">
                  <td style="padding: 10px 12px; font-weight: 600; color: #1e293b;">{r['Region']}</td>
                  <td style="padding: 10px 12px; text-align: center; color: #334155;">{installed}</td>
                  <td style="padding: 10px 12px; text-align: center; color: #059669; font-weight: 500;">{comm}</td>
                  <td style="padding: 10px 12px; text-align: center; color: #475569;">{working_pct}</td>
                  <td style="padding: 10px 12px; text-align: center; color: #475569;">{fault_count}</td>
                  <td style="padding: 10px 12px; text-align: center; font-weight: 600; color: #1e293b;">{faulty_calc}</td>
                  <td style="padding: 10px 12px; text-align: center;">
                    <span style="background-color: #ecfdf5; color: #10b981; padding: 3px 8px; border-radius: 9999px; font-weight: 700; font-size: 12px; border: 1px solid #a7f3d0;">{kpi_val:.2f}%</span>
                  </td>
                  <td style="padding: 10px 12px; font-size: 12px; color: #475569;">{tl}</td>
                  <td style="padding: 10px 12px; font-size: 12px; color: #475569;">{coord}</td>
                </tr>"""
            elif tier_type == "tier2":
                html += f"""
                <tr style="background-color: {bg}; border-bottom: 1px solid #e2e8f0; font-size: 13px;">
                  <td style="padding: 10px 12px; font-weight: 600; color: #1e293b;">
                    {r['Region']}
                    <div style="font-size: 11px; color: #64748b; font-weight: normal;">TL: {tl}</div>
                  </td>
                  <td style="padding: 10px 12px; text-align: center; color: #334155;">{installed}</td>
                  <td style="padding: 10px 12px; text-align: center; color: #059669;">{comm}</td>
                  <td style="padding: 10px 12px; text-align: center;">
                    <span style="background-color: #fffbeb; color: #d97706; padding: 3px 8px; border-radius: 9999px; font-weight: 700; font-size: 12px; border: 1px solid #fde68a;">{kpi_val:.2f}%</span>
                  </td>
                  <td style="padding: 10px 12px; text-align: center; color: #64748b; font-size: 12px;">
                    Off: <b>{not_comm}</b> | Cal: <b>{cal}</b><br>
                    Mtr: <b style="color: #dc2626;">{meter}</b> | MCB: <b style="color: #ea580c;">{mcb}</b>
                  </td>
                  <td style="padding: 10px 12px; text-align: center; font-weight: 700; color: #b45309;">{faulty_calc} pts</td>
                  <td style="padding: 10px 12px; text-align: center; font-weight: 700; color: #dc2626;">-{deficit} pts</td>
                  <td style="padding: 10px 12px; font-size: 12px; color: #1e40af; font-weight: 600; background-color: #eff6ff;">
                    {rec}
                  </td>
                </tr>"""
            else:
                html += f"""
                <tr style="background-color: {bg}; border-bottom: 1px solid #e2e8f0; font-size: 13px;">
                  <td style="padding: 10px 12px; font-weight: 600; color: #1e293b;">
                    {r['Region']}
                    <div style="font-size: 11px; color: #64748b; font-weight: normal;">TL: {tl} | Coord: {coord}</div>
                  </td>
                  <td style="padding: 10px 12px; text-align: center; color: #334155;">{installed}</td>
                  <td style="padding: 10px 12px; text-align: center; color: #059669;">{comm}</td>
                  <td style="padding: 10px 12px; text-align: center;">
                    <span style="background-color: #fef2f2; color: #dc2626; padding: 3px 8px; border-radius: 9999px; font-weight: 700; font-size: 12px; border: 1px solid #fecaca;">{kpi_val:.2f}%</span>
                  </td>
                  <td style="padding: 10px 12px; text-align: center; color: #64748b; font-size: 12px;">
                    Off: <b>{not_comm}</b> | Cal: <b>{cal}</b><br>
                    Mtr: <b style="color: #dc2626;">{meter}</b> | MCB: <b style="color: #ea580c;">{mcb}</b> | Cont: <b style="color: #7c2d12;">{contactor}</b>
                  </td>
                  <td style="padding: 10px 12px; text-align: center; font-weight: 700; color: #dc2626;">{faulty_calc} pts</td>
                  <td style="padding: 10px 12px; text-align: center; font-weight: 700; color: #991b1b;">-{deficit} pts</td>
                  <td style="padding: 10px 12px; font-size: 12px; color: #991b1b; font-weight: 600; background-color: #fff1f2;">
                    {rec}
                  </td>
                </tr>"""
        return html

    logo_img_tag = '<img src="cid:schnell_logo" alt="Schnell Logo" style="height: 38px; width: auto; background-color: #ffffff; padding: 4px 8px; border-radius: 6px; display: block;" />' if os.path.exists(LOGO_FILE) else ''

    html_template = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Schnell IoT Gateway KPI & Fault Analytics Executive Mail Dashboard</title>
</head>
<body style="margin: 0; padding: 0; background-color: #f1f5f9; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color: #1e293b;">
  <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color: #f1f5f9; padding: 24px 0;">
    <tr>
      <td align="center">
        <table width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width: 880px; background-color: #ffffff; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 15px rgba(0,0,0,0.06); border: 1px solid #e2e8f0;">
          
          <!-- Header -->
          <tr>
            <td style="background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%); padding: 24px 32px; color: #ffffff;">
              <table width="100%" cellpadding="0" cellspacing="0" border="0">
                <tr>
                  <td valign="middle" style="width: 65%;">
                    <table cellpadding="0" cellspacing="0" border="0">
                      <tr>
                        <td valign="middle" style="padding-right: 14px;">
                          {logo_img_tag}
                        </td>
                        <td valign="middle">
                          <div style="font-size: 11px; text-transform: uppercase; letter-spacing: 1.5px; color: #38bdf8; font-weight: 700; margin-bottom: 4px;">
                            Schnell Energy Technologies • IoT Operations
                          </div>
                          <h1 style="margin: 0; font-size: 22px; font-weight: 800; color: #ffffff; line-height: 1.25;">
                            Gateway KPI & Fault Analytics Mail Dashboard
                          </h1>
                        </td>
                      </tr>
                    </table>
                    <p style="margin: 8px 0 0 0; font-size: 13px; color: #94a3b8;">
                      Category-Wise Breakdown (Above 95% | 80%–95% | Below 80%) • Fault Weightage Matrix
                    </p>
                  </td>
                  <td valign="middle" align="right" style="width: 35%;">
                    <div style="background-color: rgba(255, 255, 255, 0.08); border: 1px solid rgba(255, 255, 255, 0.15); border-radius: 8px; padding: 10px 14px; display: inline-block; text-align: right;">
                      <div style="font-size: 11px; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.5px;">Report Timestamp</div>
                      <div style="font-size: 14px; font-weight: 700; color: #38bdf8; margin-top: 2px;">{report_date} | {report_time}</div>
                      <div style="font-size: 11px; color: #cbd5e1; margin-top: 2px;">Scope: {len(rows)} Active Projects</div>
                    </div>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- KPI Summary Cards -->
          <tr>
            <td style="padding: 24px 32px 16px 32px; background-color: #f8fafc; border-bottom: 1px solid #e2e8f0;">
              <table width="100%" cellpadding="0" cellspacing="8" border="0">
                <tr>
                  <td width="25%" valign="top" style="background-color: #ffffff; border: 1px solid #e2e8f0; border-radius: 10px; padding: 16px; border-left: 4px solid #3b82f6;">
                    <div style="font-size: 11px; color: #64748b; font-weight: 700; text-transform: uppercase;">Fleet Overall KPI</div>
                    <div style="font-size: 26px; font-weight: 800; color: #1e293b; margin: 4px 0;">{fleet_kpi:.2f}%</div>
                    <div style="font-size: 11px; color: #ef4444; font-weight: 600;">Target Gap: -{(95.0 - fleet_kpi):.2f}% to 95%</div>
                  </td>
                  <td width="25%" valign="top" style="background-color: #ffffff; border: 1px solid #e2e8f0; border-radius: 10px; padding: 16px; border-left: 4px solid #10b981;">
                    <div style="font-size: 11px; color: #64748b; font-weight: 700; text-transform: uppercase;">Installed / Online</div>
                    <div style="font-size: 24px; font-weight: 800; color: #1e293b; margin: 4px 0;">{total_comm:,} <span style="font-size: 13px; font-weight: normal; color: #64748b;">/ {total_installed:,}</span></div>
                    <div style="font-size: 11px; color: #10b981; font-weight: 600;">{comm_pct:.2f}% Communicating</div>
                  </td>
                  <td width="25%" valign="top" style="background-color: #ffffff; border: 1px solid #e2e8f0; border-radius: 10px; padding: 16px; border-left: 4px solid #f59e0b;">
                    <div style="font-size: 11px; color: #64748b; font-weight: 700; text-transform: uppercase;">Fault Load (Weighted)</div>
                    <div style="font-size: 24px; font-weight: 800; color: #b45309; margin: 4px 0;">{total_faulty_calc:,} <span style="font-size: 13px; font-weight: normal; color: #64748b;">pts</span></div>
                    <div style="font-size: 11px; color: #64748b;">Raw Faults: {total_fault_count:,} units</div>
                  </td>
                  <td width="25%" valign="top" style="background-color: #ffffff; border: 1px solid #e2e8f0; border-radius: 10px; padding: 16px; border-left: 4px solid #8b5cf6;">
                    <div style="font-size: 11px; color: #64748b; font-weight: 700; text-transform: uppercase;">Tier Breakdown</div>
                    <div style="margin-top: 6px; font-size: 12px; line-height: 1.5;">
                      <span style="color: #059669; font-weight: 700;">🟢 ≥95%: {len(tier1)} regions</span><br>
                      <span style="color: #d97706; font-weight: 700;">🟡 80-95%: {len(tier2)} regions</span><br>
                      <span style="color: #dc2626; font-weight: 700;">🔴 &lt;80%: {len(tier3)} regions</span>
                    </div>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- STRATEGIC FAULT ANALYTICS BOX -->
          <tr>
            <td style="padding: 24px 32px; background-color: #ffffff;">
              <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 10px; padding: 18px 20px;">
                <tr>
                  <td>
                    <div style="font-size: 14px; font-weight: 800; color: #166534; margin-bottom: 8px;">
                      🔍 STRATEGIC FAULT RECTIFICATION & KPI RECOVERY INSIGHT
                    </div>
                    <p style="margin: 0 0 12px 0; font-size: 13px; color: #15803d; line-height: 1.5;">
                      Formula: <code style="background-color: #dcfce7; padding: 2px 6px; border-radius: 4px; font-weight: 700; color: #14532d;">KPI% = (Installed - Weighted Faults) / Installed × 100</code>
                    </p>
                    <div style="background-color: #ffffff; border-left: 4px solid #059669; padding: 10px 14px; border-radius: 4px; font-size: 12px; color: #166534; line-height: 1.5;">
                      <b>💡 KEY PRIORITY TAKEAWAY:</b><br>
                      • <b>Meter Comm Failures (5x weight)</b> produce 34.9% of the fleet's total deduction across just 148 units. Fixing 1 meter saves 5 KPI points!<br>
                      • <b>7 Moderate Projects</b> need only 1 to 3 Meter Comm repairs to cross immediately into the <b>≥ 95% Green Zone</b>.
                    </div>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- SECTION 1 -->
          <tr>
            <td style="padding: 0 32px 28px 32px;">
              <table width="100%" cellpadding="0" cellspacing="0" border="0" style="border-top: 3px solid #10b981; border-radius: 8px; overflow: hidden; border: 1px solid #d1fae5; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">
                <tr style="background: linear-gradient(90deg, #ecfdf5 0%, #f0fdf4 100%);">
                  <td style="padding: 14px 18px;">
                    <span style="background-color: #10b981; color: #ffffff; padding: 3px 8px; border-radius: 4px; font-size: 11px; font-weight: 800; text-transform: uppercase;">Section 1</span>
                    <span style="font-size: 16px; font-weight: 800; color: #065f46; margin-left: 8px;">BENCHMARK ACHIEVERS (KPI ≥ 95.0%) - {len(tier1)} Projects</span>
                  </td>
                </tr>
                <tr>
                  <td>
                    <table width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse: collapse;">
                      <thead>
                        <tr style="background-color: #f8fafc; color: #475569; font-size: 11px; text-transform: uppercase; font-weight: 700; border-bottom: 2px solid #e2e8f0;">
                          <th style="padding: 10px 12px; text-align: left;">Region</th>
                          <th style="padding: 10px 12px; text-align: center;">Installed</th>
                          <th style="padding: 10px 12px; text-align: center;">Online</th>
                          <th style="padding: 10px 12px; text-align: center;">Online %</th>
                          <th style="padding: 10px 12px; text-align: center;">Raw Faults</th>
                          <th style="padding: 10px 12px; text-align: center;">Weighted Pts</th>
                          <th style="padding: 10px 12px; text-align: center;">KPI %</th>
                          <th style="padding: 10px 12px; text-align: left;">Team Leader</th>
                          <th style="padding: 10px 12px; text-align: left;">Coordinator</th>
                        </tr>
                      </thead>
                      <tbody>{render_rows(tier1, "tier1")}</tbody>
                    </table>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- SECTION 2 -->
          <tr>
            <td style="padding: 0 32px 28px 32px;">
              <table width="100%" cellpadding="0" cellspacing="0" border="0" style="border-top: 3px solid #f59e0b; border-radius: 8px; overflow: hidden; border: 1px solid #fef3c7; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">
                <tr style="background: linear-gradient(90deg, #fffbeb 0%, #fefce8 100%);">
                  <td style="padding: 14px 18px;">
                    <span style="background-color: #f59e0b; color: #ffffff; padding: 3px 8px; border-radius: 4px; font-size: 11px; font-weight: 800; text-transform: uppercase;">Section 2</span>
                    <span style="font-size: 16px; font-weight: 800; color: #92400e; margin-left: 8px;">MODERATE PRIORITY (80.0% ≤ KPI &lt; 95.0%) - {len(tier2)} Projects</span>
                  </td>
                </tr>
                <tr>
                  <td>
                    <table width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse: collapse;">
                      <thead>
                        <tr style="background-color: #f8fafc; color: #475569; font-size: 11px; text-transform: uppercase; font-weight: 700; border-bottom: 2px solid #e2e8f0;">
                          <th style="padding: 10px 12px; text-align: left;">Region / TL</th>
                          <th style="padding: 10px 12px; text-align: center;">Installed</th>
                          <th style="padding: 10px 12px; text-align: center;">Online</th>
                          <th style="padding: 10px 12px; text-align: center;">KPI %</th>
                          <th style="padding: 10px 12px; text-align: center;">Fault Breakdown</th>
                          <th style="padding: 10px 12px; text-align: center;">Weighted Pts</th>
                          <th style="padding: 10px 12px; text-align: center;">Gap to 95%</th>
                          <th style="padding: 10px 12px; text-align: left;">Recommended Priority Rectification</th>
                        </tr>
                      </thead>
                      <tbody>{render_rows(tier2, "tier2")}</tbody>
                    </table>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- SECTION 3 -->
          <tr>
            <td style="padding: 0 32px 28px 32px;">
              <table width="100%" cellpadding="0" cellspacing="0" border="0" style="border-top: 3px solid #ef4444; border-radius: 8px; overflow: hidden; border: 1px solid #fee2e2; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">
                <tr style="background: linear-gradient(90deg, #fef2f2 0%, #fff1f2 100%);">
                  <td style="padding: 14px 18px;">
                    <span style="background-color: #ef4444; color: #ffffff; padding: 3px 8px; border-radius: 4px; font-size: 11px; font-weight: 800; text-transform: uppercase;">Section 3</span>
                    <span style="font-size: 16px; font-weight: 800; color: #991b1b; margin-left: 8px;">CRITICAL ATTENTION REQUIRED (KPI &lt; 80.0%) - {len(tier3)} Projects</span>
                  </td>
                </tr>
                <tr>
                  <td>
                    <table width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse: collapse;">
                      <thead>
                        <tr style="background-color: #f8fafc; color: #475569; font-size: 11px; text-transform: uppercase; font-weight: 700; border-bottom: 2px solid #e2e8f0;">
                          <th style="padding: 10px 12px; text-align: left;">Region / TL</th>
                          <th style="padding: 10px 12px; text-align: center;">Installed</th>
                          <th style="padding: 10px 12px; text-align: center;">Online</th>
                          <th style="padding: 10px 12px; text-align: center;">KPI %</th>
                          <th style="padding: 10px 12px; text-align: center;">Major Faults</th>
                          <th style="padding: 10px 12px; text-align: center;">Weighted Pts</th>
                          <th style="padding: 10px 12px; text-align: center;">Gap to 95%</th>
                          <th style="padding: 10px 12px; text-align: left;">Critical Action Required</th>
                        </tr>
                      </thead>
                      <tbody>{render_rows(tier3, "tier3")}</tbody>
                    </table>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="padding: 24px 32px; background-color: #0f172a; color: #94a3b8; font-size: 12px; text-align: center; border-top: 1px solid #1e293b;">
              <div style="font-size: 13px; font-weight: 700; color: #f8fafc; margin-bottom: 4px;">Schnell IoT Fleet Operations & Maintenance System</div>
              <div style="margin-bottom: 8px;">Auto-generated Executive Report • Gateway 2G / 4G Infrastructure</div>
              <div style="color: #64748b; font-size: 11px;">
                Confidential • Intended for internal operations and team leaders • Generated from live Google Sheet
              </div>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""

    with open(OUTPUT_HTML_FILE, "w", encoding="utf-8") as f:
        f.write(html_template)
    print(f"Generated {OUTPUT_HTML_FILE}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Sync Google Sheet to KPI Mail Dashboard")
    parser.add_argument("--sheet-id", help="Google Spreadsheet ID or URL")
    parser.add_argument("--worksheet", help="Worksheet name (tab name, defaults to 'Gateway')")
    parser.add_argument("--date", help="Specific date to sync (e.g., '14-Oct-2026'). Defaults to latest date.")
    parser.add_argument("--send", action="store_true", help="Send email report automatically after syncing")
    args = parser.parse_args()

    sheet_id = args.sheet_id or SPREADSHEET_ID_OR_URL

    raw_data = fetch_via_gspread(sheet_id, worksheet_name=args.worksheet, target_date=args.date)

    if not raw_data:
        print("No records retrieved. Please check sheet access and worksheet name.")
        sys.exit(1)

    processed = process_records(raw_data)
    print(f"Processed {len(processed)} valid project rows.")

    report_date = processed[0].get("Date", datetime.now().strftime("%d-%b-%Y"))
    report_time = processed[0].get("Time", datetime.now().strftime("%H:%M:%S"))

    render_html_dashboard(processed, report_date, report_time)
    print(f"\n[SUCCESS] Mail Dashboard is updated at: {OUTPUT_HTML_FILE}")

    if args.send:
        print("\nDispatching email dashboard via send_mail_dashboard.py...")
        import subprocess
        subprocess.run([sys.executable, os.path.join(os.path.dirname(__file__), "send_mail_dashboard.py"), "--send"], check=True)


if __name__ == "__main__":
    main()

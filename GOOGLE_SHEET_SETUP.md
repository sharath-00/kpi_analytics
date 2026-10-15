# How to Connect Your Google Sheet to the Mail Dashboard

You can sync your live Google Sheet using either **Method 1 (Official Google Cloud API with Service Account)** or **Method 2 (Instant URL Link - Zero Setup)**.

All required Python libraries (`gspread`, `google-api-python-client`, `requests`, `pandas`) are **already installed** on your system.

---

## Method 1: Google Sheets API v4 (Official Service Account)
*Recommended for private enterprise Google Sheets.*

### Step 1: Create a Service Account in Google Cloud Console
1. Go to the [Google Cloud Console](https://console.cloud.google.com/).
2. Create a new project (e.g., `Schnell-IoT-KPI`).
3. In the search bar at the top, search for and **enable** these two APIs:
   - **Google Sheets API**
   - **Google Drive API**
4. In the left navigation, go to **IAM & Admin** $\to$ **Service Accounts**.
5. Click **Create Service Account**:
   - Service account name: `gateway-kpi-sync`
   - Click **Create and Continue**, then click **Done**.
6. Click on the newly created service account, go to the **Keys** tab:
   - Click **Add Key** $\to$ **Create new key**.
   - Select **JSON** and click **Create**.
   - A `.json` file will download to your computer.

### Step 2: Save the Key to Your Project
Rename the downloaded JSON file to `service_account.json` and place it in your folder:
```
d:\Schnell\gateway_kpi\service_account.json
```

### Step 3: Share Your Google Sheet with the Service Account
1. Open `service_account.json` in a text editor and copy the `client_email` value (it looks like: `gateway-kpi-sync@your-project.iam.gserviceaccount.com`).
2. Open your Google Sheet in your browser.
3. Click the **Share** button in the top right.
4. Paste the service account email and grant it **Viewer** permission.

### Step 4: Run the Sync Command
```powershell
python d:\Schnell\gateway_kpi\sync_google_sheet.py --sheet-id "YOUR_GOOGLE_SHEET_URL_OR_ID"
```

---

## Method 2: Instant URL Link (Zero GCP Setup Required)
*Recommended if you want live data in 10 seconds without creating a Google Cloud project.*

### Step 1: Set Google Sheet Sharing
1. Open your Google Sheet.
2. Click **Share** (top right) $\to$ Change General access to **"Anyone with the link can view"** (or within your organization).
3. Copy the URL from your browser address bar (e.g. `https://docs.google.com/spreadsheets/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms/edit#gid=0`).

### Step 2: Run the Sync Command
```powershell
python d:\Schnell\gateway_kpi\sync_google_sheet.py --sheet-id "PASTE_YOUR_FULL_SHEET_URL_HERE"
```

---

## What Happens When You Run the Script?
1. Fetches the latest rows from your live Google Sheet.
2. Recalculates:
   - Working % and Communication rates
   - Weighted penalties (Contactor 10x, Meter Comm Fail 5x, MCB Trip 5x, Cal 1x, Offline 1x)
   - Category Tiers: Section 1 (≥95%), Section 2 (80%–95%), Section 3 (<80%)
   - Deficit to 95% target & exact targeted repair steps.
3. Automatically updates [mail_dashboard.html](file:///d:/Schnell/gateway_kpi/mail_dashboard.html).
4. If you add `--send`, it automatically dispatches the updated email to management and team leaders via SMTP!

```powershell
# Sync and auto-send email in one command:
python d:\Schnell\gateway_kpi\sync_google_sheet.py --sheet-id "YOUR_SHEET_URL" --send
```

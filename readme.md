# Email Blacklist Monitor

A Python application that continuously monitors an Outlook email account for incoming emails with attachments (Excel, CSV, PDF, images) and checks their content against a blacklist database. When matches are found based on CIN, name combinations, or IMM numbers, automatic alert emails are sent.

## Installation

1. **Clone the repository**:
   ```bash
   git clone <repository-url>
   cd email-blacklist-monitor
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

## Azure Portal Setup

### 1. Create Azure AD App Registration

1. Go to [Azure Portal](https://portal.azure.com)
2. Navigate to **App registrations**
3. Click **New registration**
4. Configure:
   - **Name**: Email Blacklist Monitor
   - **Supported account types**: Accounts in any organizational directory (Any Microsoft Entra ID tenant - Multitenant) and personal Microsoft accounts (e.g. Skype, Xbox)
   - **Redirect URI**: `http://localhost:8000` (Web)
5. Note the **Application (client) ID** 

### 2. Set API Permissions

1. Go to **API permissions** → **Add a permission**
2. Select **Microsoft Graph** → **Application permissions**
3. Add these permissions:
   - `Mail.Read`
   - `Mail.Send`

4. Click **Grant admin consent**

## Environment Configuration

Create a `.env` file in the project root with your Azure details:

```env
# Azure config
CLIENT_ID = your_application_id_here
TENANT_ID =  common
AUTHORITY = https://login.microsoftonline.com/common
SCOPE = https://graph.microsoft.com/Mail.Read https://graph.microsoft.com/Mail.Send

#
MONITOR_EMAIL =  your_monitor_email
ALERT_EMAIL =  your_alert_email
BLACKLIST_FILE = blacklist.csv
CHECK_INTERVAL = 60
TESSERACT_PATH = PATH\\TO\\TESSERACT\\INSTALLATION\\tesseract.exe
```

## Blacklist CSV Format

Create a `blacklist.csv` file with the following columns:

```csv
first_name,last_name,cin,vehicle_make,imm,color
John,Doe,AB123456,Toyota,1234ABC,Blue
Jane,Smith,CD789012,Honda,5678DEF,Red
...
```

## Usage

```bash
python exercice.py
```

The application will:
1. Monitor the specified outlook email account
2. Process attachments from incoming emails (CSV,EXCEL,PDF,IMAGES)
3. Check for matches against the blacklist
4. Send alert emails when matches are found
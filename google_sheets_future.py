"""
Optional future module.

Use this when you are ready to push results to Google Sheets instead of only Excel.

You will need:
pip install gspread google-auth

Basic plan:
1. Create a Google Cloud project
2. Enable Google Sheets API
3. Create a service account
4. Download service-account.json
5. Share the Google Sheet with the service account email
6. Load the tracker dataframe and upload it
"""

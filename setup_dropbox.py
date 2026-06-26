"""
One-time Dropbox OAuth2 setup — obtains a long-lived refresh token.

Usage:
    python setup_dropbox.py

This opens your browser to authorize the app. After you approve,
paste the authorization code here. The refresh token will be printed
for you to add to your .env file.

Prerequisites:
  1. Go to https://www.dropbox.com/developers/apps
  2. Create an app:
     Choose "Scoped access" → "Full Dropbox"
     (Do NOT choose "Dropbox Business API" as that requires team admin rights)
  3. Under Permissions, enable:
     - files.content.write, files.content.read
     - sharing.write, sharing.read
  4. Copy your App Key and App Secret
"""
import webbrowser
import sys

try:
    import dropbox
    from dropbox import DropboxOAuth2FlowNoRedirect
except ImportError:
    print("Error: dropbox package not installed. Run: pip install dropbox")
    sys.exit(1)


def setup():
    print("\n" + "=" * 60)
    print("  DROPBOX OAUTH2 SETUP — Get Refresh Token")
    print("=" * 60)

    print("""
You need your App Key and App Secret from:
  https://www.dropbox.com/developers/apps

If you haven't created an app yet:
  1. Click "Create app"
  2. Choose "Scoped access" → "Full Dropbox"
     (*Even if you are on a Business team, choose Scoped Access*)
  3. Name it something like "VOD Clipper"
  4. Under Permissions tab, enable:
     - files.content.write
     - files.content.read
     - sharing.write
     - sharing.read
  5. Click "Submit" to save permissions
""")

    app_key = input("App Key: ").strip()
    if not app_key:
        print("Error: App Key is required")
        sys.exit(1)

    app_secret = input("App Secret: ").strip()
    if not app_secret:
        print("Error: App Secret is required")
        sys.exit(1)

    # Start OAuth2 flow (no PKCE since we have app_secret)
    auth_flow = DropboxOAuth2FlowNoRedirect(
        app_key,
        consumer_secret=app_secret,
        token_access_type="offline",  # This gives us a refresh token
    )

    authorize_url = auth_flow.start()

    print(f"\n{'~' * 60}")
    print("Opening your browser to authorize the app...")
    print(f"If it doesn't open, go to:\n\n  {authorize_url}\n")
    print(f"{'~' * 60}")

    webbrowser.open(authorize_url)

    auth_code = input("\nPaste the authorization code here: ").strip()
    if not auth_code:
        print("Error: Authorization code is required")
        sys.exit(1)

    print("\nExchanging code for token...")
    try:
        oauth_result = auth_flow.finish(auth_code)
    except Exception as e:
        print(f"\nError: Could not complete OAuth flow: {e}")
        print("Make sure you copied the full authorization code.")
        sys.exit(1)

    refresh_token = oauth_result.refresh_token

    # Test the connection (with namespace routing to check for team space)
    dbx = dropbox.Dropbox(
        oauth2_refresh_token=refresh_token,
        app_key=app_key,
        app_secret=app_secret,
    )
    account = dbx.users_get_current_account()
    
    # Check if this is a team space account
    root_ns = account.root_info.root_namespace_id
    is_team_space = (account.root_info.home_namespace_id != root_ns)
    
    status = "Connected to Team Space" if is_team_space else "Connected as Personal"

    print(f"\n{'=' * 60}")
    print(f"  SUCCESS — {status}: {account.name.display_name}")
    print(f"{'=' * 60}")
    print(f"\nAdd these to your .env file:\n")
    print(f"  DROPBOX_APP_KEY={app_key}")
    print(f"  DROPBOX_APP_SECRET={app_secret}")
    print(f"  DROPBOX_REFRESH_TOKEN={refresh_token}")

    print(f"\nYou can remove the old DROPBOX_ACCESS_TOKEN line.")
    print(f"The refresh token never expires (unless you revoke it).")
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    setup()

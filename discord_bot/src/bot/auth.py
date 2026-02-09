import os
import threading
import time
import hmac
import hashlib
import requests
from flask import Flask, redirect, url_for, jsonify, session, request
from flask_dance.contrib.github import make_github_blueprint, github
from dotenv import load_dotenv
from werkzeug.middleware.proxy_fix import ProxyFix
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

load_dotenv()

# Global state for OAuth sessions (keyed by Discord user ID)
oauth_sessions = {}
oauth_sessions_lock = threading.Lock()

# Background thread to clean up old OAuth sessions (prevents memory leak)
def cleanup_old_oauth_sessions():
    """Clean up OAuth sessions older than 10 minutes to prevent memory leak."""
    while True:
        time.sleep(300)  # Check every 5 minutes
        with oauth_sessions_lock:
            current_time = time.time()
            expired_sessions = [
                user_id for user_id, session_data in oauth_sessions.items()
                if current_time - session_data.get('created_at', current_time) > 600  # 10 min
            ]
            for user_id in expired_sessions:
                del oauth_sessions[user_id]
                print(f"Cleaned up expired OAuth session for user {user_id}")

# Start cleanup thread
_cleanup_thread = threading.Thread(target=cleanup_old_oauth_sessions, daemon=True)
_cleanup_thread.start()

def create_oauth_app():
    """
    Create and configure the Flask OAuth application.
    This returns a Flask app that can be run alongside the Discord bot.
    """
    app = Flask(__name__)
    app.secret_key = os.getenv("SECRET_KEY", "super-secret-oauth-key")
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
    
    # Set OAuth transport to allow HTTP in development, HTTPS in production
    if os.getenv("DEVELOPMENT"):
        os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
    
    # Get the base URL for OAuth callbacks (Cloud Run URL)
    base_url = os.getenv("OAUTH_BASE_URL")
    if not base_url:
        raise ValueError("OAUTH_BASE_URL environment variable is required")
    
    # OAuth blueprint with custom callback URL (avoiding Flask-Dance auto routes)
    github_blueprint = make_github_blueprint(
        client_id=os.getenv("GITHUB_CLIENT_ID"),
        client_secret=os.getenv("GITHUB_CLIENT_SECRET"),
        redirect_url=f"{base_url}/auth/callback",
        scope="read:org"
    )
    app.register_blueprint(github_blueprint, url_prefix="/login")

    state_serializer = URLSafeTimedSerializer(app.secret_key, salt="github-app-install")
    
    @app.route("/")
    def index():
        return jsonify({
            "service": "DisgitBot - GitHub Discord Integration",
            "status": "Ready",
            "endpoints": {
                "invite_bot": "/invite",
                "setup": "/setup",
                "github_auth": "/auth/start/<discord_user_id>",
                "github_app_install": "/github/app/install",
                "github_app_setup_callback": "/github/app/setup",
                "github_webhook": "/github/webhook"
            }
        })
    
    @app.route("/github/webhook", methods=["POST"])
    def github_webhook():
        """
        GitHub webhook endpoint for SaaS PR automation.
        Processes pull_request events from any org that installs the GitHub App.
        """
        import asyncio
        from threading import Thread
        
        # PR automation is disabled - /set_webhook command removed
        # To re-enable: restore /set_webhook command in notification_commands.py
        print("PR automation is disabled (feature removed)")
        return jsonify({
            "message": "PR automation is not available",
            "status": "not_implemented"
        }), 501
        
        # NOTE: Code below is kept for future re-enablement
        # 1. Verify webhook signature (MANDATORY)
        webhook_secret = os.getenv("GITHUB_WEBHOOK_SECRET")
        if not webhook_secret:
            print("ERROR: GITHUB_WEBHOOK_SECRET not configured - rejecting webhook")
            return jsonify({
                "error": "Webhook not configured",
                "message": "GITHUB_WEBHOOK_SECRET environment variable must be set"
            }), 500
        
        # 2. Parse event type
        event_type = request.headers.get("X-GitHub-Event")
        delivery_id = request.headers.get("X-GitHub-Delivery")
        
        print(f"Received webhook: event={event_type}, delivery_id={delivery_id}")
        
        if event_type == "ping":
            return jsonify({"message": "pong", "delivery_id": delivery_id}), 200
        
        # 3. Handle pull_request events
        if event_type != "pull_request":
            print(f"Ignoring event type: {event_type}")
            return jsonify({"message": f"Ignored event: {event_type}"}), 200
        
        try:
            payload = request.get_json()
            action = payload.get("action")
            
            # Only process opened and synchronize (push to PR) actions
            if action not in ["opened", "synchronize", "reopened"]:
                print(f"Ignoring PR action: {action}")
                return jsonify({"message": f"Ignored action: {action}"}), 200
            
            pr = payload.get("pull_request", {})
            repo = payload.get("repository", {})
            
            pr_number = pr.get("number")
            repo_full_name = repo.get("full_name")  # e.g., "owner/repo"
            
            if not pr_number or not repo_full_name:
                return jsonify({"error": "Missing PR number or repo"}), 400
            
            print(f"Processing PR #{pr_number} in {repo_full_name} (action: {action})")
            
            # 4. Trigger PR automation in background thread
            def run_pr_automation():
                try:
                    from pr_review.main import PRReviewSystem
                    
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    
                    system = PRReviewSystem()
                    results = loop.run_until_complete(
                        system.process_pull_request(repo_full_name, pr_number)
                    )
                    
                    print(f"PR automation completed: {results.get('status', 'unknown')}")
                    loop.close()
                    
                except Exception as e:
                    print(f"PR automation failed: {e}")
                    import traceback
                    traceback.print_exc()
            
            # Start background thread for PR processing
            Thread(target=run_pr_automation, daemon=True).start()
            
            return jsonify({
                "message": "PR automation triggered",
                "pr_number": pr_number,
                "repository": repo_full_name,
                "action": action
            }), 202
            
        except Exception as e:
            print(f"Error processing webhook: {e}")
            import traceback
            traceback.print_exc()
            return jsonify({"error": str(e)}), 500
    
    @app.route("/invite")
    def invite_bot():
        """Discord bot invitation endpoint"""
        
        # Your bot's client ID from Discord Developer Portal
        bot_client_id = os.getenv("DISCORD_BOT_CLIENT_ID", "YOUR_BOT_CLIENT_ID")
        
        # Required permissions for the bot
        permissions = "552172899344"  # Manage Roles + View Channels + Send Messages + Use Slash Commands
        
        discord_invite_url = (
            f"https://discord.com/oauth2/authorize?"
            f"client_id={bot_client_id}&"
            f"permissions={permissions}&"
            f"integration_type=0&"
            f"scope=bot+applications.commands"
        )
        
        setup_url = f"{base_url}/setup"
        
        # Enhanced landing page with modern design
        landing_page = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Add DisgitBot to Discord</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@500&display=swap" rel="stylesheet">
    
    <style>
        body {{
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            margin: 0; padding: 20px;
            background: radial-gradient(circle at top left, #2c2e33 0%, #0f1012 100%);
            color: #e1e1e1;
            height: 100vh;
            display: flex; align-items: center; justify-content: center;
            box-sizing: border-box;
            line-height: 1.6;
            overflow: hidden;
        }}
        
        .card {{
            background: rgba(30, 31, 34, 0.75);
            backdrop-filter: blur(16px);
            -webkit-backdrop-filter: blur(16px);
            border: 1px solid rgba(255, 255, 255, 0.08);
            padding: 40px; border-radius: 24px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.6);
            width: 100%; max-width: 500px;
        }}
        
        h1 {{ 
            color: #ffffff; margin: 0 0 10px 0; 
            font-size: 24px; font-weight: 800;
            letter-spacing: -0.5px;
            background: linear-gradient(90deg, #fff, #b9bbbe);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }}
        
        .subtitle {{ 
            color: #b9bbbe; margin-bottom: 24px; 
            font-size: 15px; font-weight: 400;
        }}
        
        .btn {{
            background: linear-gradient(135deg, #5865f2 0%, #4752c4 100%);
            color: white; padding: 12px 24px;
            border: none; border-radius: 12px; font-weight: 600;
            cursor: pointer; font-size: 15px; width: 100%;
            transition: transform 0.2s, box-shadow 0.2s, filter 0.2s;
            text-align: center; 
            display: inline-flex; align-items: center; justify-content: center; gap: 12px;
            text-decoration: none;
            box-shadow: 0 8px 20px rgba(88, 101, 242, 0.25);
            box-sizing: border-box;
            position: relative; 
             
        }}

        .btn::before {{
            content: '';
            position: absolute;
            top: 0;
            left: -100%; 
            width: 100%;
            height: 100%;
            background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.3), transparent);
            transition: left 0.5s; 
        }}
        
        .btn:hover {{
            transform: translateY(-2px);
            box-shadow: 0 12px 30px rgba(88, 101, 242, 0.4);
            filter: brightness(1.1);
        }}

        .btn:hover::before {{
            left: 100%; 
        }}

        .discord-icon {{ width: 24px; height: 24px; fill: white; }}
        
        .steps-container {{
            margin-top: 40px;
            border-top: 1px solid rgba(255,255,255,0.08);
            padding-top: 30px;
        }}

        .section-title {{
            font-size: 14px; text-transform: uppercase; letter-spacing: 1px;
            color: #949BA4; margin-bottom: 20px; font-weight: 700;
        }}

        .step {{
            display: flex; gap: 15px; margin-bottom: 20px;
            position: relative;
        }}
        
        .step-number {{
            min-width: 24px; height: 24px;
            background: rgba(255,255,255,0.1);
            color: #fff; border-radius: 50%;
            display: flex; align-items: center; justify-content: center;
            font-size: 12px; font-weight: 700;
            margin-top: 2px;
        }}
        
        .step-content {{ font-size: 14px; color: #dcddde; }}
        
        code {{
            background: rgba(88, 101, 242, 0.15);
            border: 1px solid rgba(88, 101, 242, 0.3);
            padding: 4px 8px; border-radius: 6px;
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.9em; color: #8ea0ff;
            display: inline-block; margin-top: 4px;
        }}

        .features-grid {{
            display: grid; grid-template-columns: 1fr 1fr; gap: 10px;
            margin-top: 30px;
        }}
        
        .feature-item {{
            background: rgba(255,255,255,0.03);
            padding: 10px 15px; border-radius: 8px;
            font-size: 13px; color: #b9bbbe;
            display: flex; align-items: center; gap: 8px;
        }}

        @media (max-width: 550px) {{
            .card {{ 
                width: 90%; 
                padding: 30px; 
            }}
            h1 {{ font-size: 22px; }}
        }}
        
        @media (max-height: 700px) {{
            .card {{ padding: 25px; }}
            .subtitle {{ margin-bottom: 20px; }}
            .btn {{ padding: 10px 20px; }}
        }}
    </style>
</head>
<body>
    <div class="card">
        <h1>Add DisgitBot</h1>
        <p class="subtitle">Track GitHub contributions and manage roles automatically in your Discord server.</p>

        <a href="{discord_invite_url}" class="btn">
            <svg class="discord-icon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 127.14 96.36">
                <path d="M107.7,8.07A105.15,105.15,0,0,0,81.47,0a72.06,72.06,0,0,0-3.36,6.83A97.68,97.68,0,0,0,49,6.83,72.37,72.37,0,0,0,45.64,0,105.89,105.89,0,0,0,19.39,8.09C2.79,32.65-1.71,56.6.54,80.21h0A105.73,105.73,0,0,0,32.71,96.36,77.11,77.11,0,0,0,39.6,85.25a68.42,68.42,0,0,1-10.85-5.18c.91-.66,1.8-1.34,2.66-2a75.57,75.57,0,0,0,64.32,0c.87.71,1.76,1.39,2.66,2a68.68,68.68,0,0,1-10.87,5.19,77,77,0,0,0,6.89,11.1A105.89,105.89,0,0,0,126.6,80.22c1.24-18.87-3.23-41.61-18.9-72.15ZM42.45,65.69C36.18,65.69,31,60,31,53s5-12.74,11.43-12.74S54,46,53.89,53,48.84,65.69,42.45,65.69Zm42.24,0C78.41,65.69,73.25,60,73.25,53s5-12.74,11.44-12.74S96.23,46,96.12,53,91.08,65.69,84.69,65.69Z"/>
            </svg>
            Add to Discord
        </a>

        <div class="steps-container">
            <div class="section-title">Setup Required After Adding</div>
            
            <div class="step">
                <div class="step-number">1</div>
                <div class="step-content">
                    <strong>Authorize Bot:</strong> Click the button above to add the bot to your server.
                </div>
            </div>

            <div class="step">
                <div class="step-number">2</div>
                <div class="step-content">
                    <strong>Configuration:</strong> Visit the setup dashboard:<br>
                    <code>{setup_url}</code>
                </div>
            </div>

            <div class="step">
                <div class="step-number">3</div>
                <div class="step-content">
                    <strong>Install GitHub App:</strong> Select which repositories you want to track.
                </div>
            </div>
            
             <div class="step">
                <div class="step-number">4</div>
                <div class="step-content">
                    <strong>Link Accounts:</strong> Users can run <code>/link</code> in Discord.
                </div>
            </div>
        </div>

        <div class="features-grid">
            <div class="feature-item">📊 Real-time Stats</div>
            <div class="feature-item">🤖 Auto Roles</div>
            <div class="feature-item">📈 Analytics Charts</div>
            <div class="feature-item">🔊 Voice Updates</div>
        </div>
    </div>
</body>
</html>
"""
        
        return landing_page
    
    @app.route("/auth/start/<discord_user_id>")
    def start_oauth(discord_user_id):
        """Start OAuth flow for a specific Discord user"""
        try:
            with oauth_sessions_lock:
                # Clear any existing session for this user
                oauth_sessions[discord_user_id] = {
                    'status': 'pending',
                    'created_at': time.time()
                }
            
            # Store user ID in session for callback
            session['discord_user_id'] = discord_user_id
            
            print(f"Starting OAuth for Discord user: {discord_user_id}")
            
            # Redirect to GitHub OAuth
            return redirect(url_for("github.login"))
            
        except Exception as e:
            print(f"Error starting OAuth: {e}")
            return jsonify({"error": "Failed to start authentication"}), 500
    
    @app.route("/auth/callback")
    def github_callback():
        """Handle GitHub OAuth callback for user account linking."""
        try:
            discord_user_id = session.get('discord_user_id')
            
            if not discord_user_id:
                return "Authentication failed: No Discord user session", 400

            if not github.authorized:
                print("GitHub OAuth not authorized")
                with oauth_sessions_lock:
                    oauth_sessions[discord_user_id] = {
                        'status': 'failed',
                        'error': 'GitHub authorization failed'
                    }
                return "GitHub authorization failed", 400

            resp = github.get("/user")
            if not resp.ok:
                print(f"GitHub API call failed: {resp.status_code}")
                with oauth_sessions_lock:
                    oauth_sessions[discord_user_id] = {
                        'status': 'failed',
                        'error': 'Failed to fetch GitHub user info'
                    }
                return "Failed to fetch GitHub user information", 400

            github_user = resp.json()
            github_username = github_user.get("login")

            if not github_username:
                print("No GitHub username found")
                with oauth_sessions_lock:
                    oauth_sessions[discord_user_id] = {
                        'status': 'failed',
                        'error': 'No GitHub username found'
                    }
                return "Failed to get GitHub username", 400

            with oauth_sessions_lock:
                oauth_sessions[discord_user_id] = {
                    'status': 'completed',
                    'github_username': github_username
                }

            session.pop('discord_user_id', None)

            print(f"OAuth completed for {github_username} (Discord: {discord_user_id})")

            return f"""
            <html>
            <head><title>Authentication Successful</title></head>
            <body style="font-family: Arial, sans-serif; text-align: center; padding: 50px;">
                <h1>Authentication Successful!</h1>
                <p>Your Discord account has been linked to GitHub user: <strong>{github_username}</strong></p>
                <p>You can now close this tab and return to Discord.</p>
                <script>
                    // Auto-close after 3 seconds
                    setTimeout(function() {{
                        window.close();
                    }}, 3000);
                </script>
            </body>
            </html>
            """

        except Exception as e:
            print(f"Error in OAuth callback: {e}")
            return f"Authentication failed: {str(e)}", 500

    @app.route("/github/app/install")
    def github_app_install():
        """Redirect server owners to install the DisgitBot GitHub App."""
        from flask import request

        guild_id = request.args.get('guild_id')
        guild_name = request.args.get('guild_name', 'your server')

        if not guild_id:
            return "Error: No Discord server information received", 400

        app_slug = os.getenv("GITHUB_APP_SLUG")
        if not app_slug:
            return "Server configuration error: missing GITHUB_APP_SLUG", 500

        state = state_serializer.dumps({'guild_id': str(guild_id), 'guild_name': guild_name})

        install_url = f"https://github.com/apps/{app_slug}/installations/new?state={state}"
        return redirect(install_url)

    @app.route("/github/app/setup")
    def github_app_setup():
        """GitHub App 'Setup URL' callback: stores installation ID for a Discord server."""
        from flask import request, render_template_string
        from shared.firestore import get_mt_client
        from datetime import datetime, timedelta
        from src.services.github_app_service import GitHubAppService

        installation_id = request.args.get('installation_id')
        state = request.args.get('state', '')

        if not installation_id or not state:
            return "Missing installation_id or state", 400

        try:
            payload = state_serializer.loads(state, max_age=60 * 60 * 24 * 7)  # 7 days for org approval
        except SignatureExpired:
            return "Setup link expired. Please restart setup from Discord.", 400
        except BadSignature:
            return "Invalid setup state. Please restart setup from Discord.", 400

        guild_id = str(payload.get('guild_id', ''))
        guild_name = payload.get('guild_name', 'your server')
        if not guild_id:
            return "Invalid setup state (missing guild_id). Please restart setup from Discord.", 400

        gh_app = GitHubAppService()
        installation = gh_app.get_installation(int(installation_id))
        if not installation:
            return "Failed to fetch installation details from GitHub.", 500

        account = installation.get('account') or {}
        github_account = account.get('login')
        github_account_type = account.get('type')

        github_org = github_account
        is_personal_install = github_account_type == 'User'

        mt_client = get_mt_client()
        existing_config = mt_client.get_server_config(guild_id) or {}
        success = mt_client.set_server_config(guild_id, {
            **existing_config,
            'github_org': github_org,
            'github_installation_id': int(installation_id),
            'github_account': github_account,
            'github_account_type': github_account_type,
            'setup_source': 'github_app',
            'created_at': datetime.now().isoformat(),
            'setup_completed': True
        })

        if not success:
            return "Error: Failed to save configuration", 500

        def trigger_initial_sync(org_name: str) -> bool:
            """Trigger the GitHub Actions pipeline once after setup."""
            token = os.getenv("GITHUB_TOKEN")
            repo_owner = os.getenv("REPO_OWNER")
            repo_name = os.getenv("REPO_NAME", "disgitbot")
            ref = os.getenv("WORKFLOW_REF", "main")

            if not token or not repo_owner:
                print("Skipping pipeline trigger: missing GITHUB_TOKEN or REPO_OWNER")
                return False

            existing_config = mt_client.get_server_config(guild_id) or {}
            last_trigger = existing_config.get("initial_sync_triggered_at")
            if last_trigger:
                try:
                    last_dt = datetime.fromisoformat(last_trigger)
                    if datetime.now() - last_dt < timedelta(minutes=10):
                        print("Skipping pipeline trigger: recent sync already triggered")
                        return False
                except ValueError:
                    pass

            url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/actions/workflows/discord_bot_pipeline.yml/dispatches"
            headers = {
                "Authorization": f"token {token}",
                "Accept": "application/vnd.github+json",
            }
            payload = {
                "ref": ref,
                "inputs": {
                    "organization": org_name
                }
            }

            try:
                resp = requests.post(url, headers=headers, json=payload, timeout=20)
                if resp.status_code in (201, 204):
                    mt_client.set_server_config(guild_id, {
                        **existing_config,
                        "initial_sync_triggered_at": datetime.now().isoformat()
                    })
                    return True
                print(f"Failed to trigger pipeline: {resp.status_code} {resp.text[:200]}")
            except Exception as exc:
                print(f"Error triggering pipeline: {exc}")
            return False


        sync_triggered = trigger_initial_sync(github_org)

        success_page = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Setup Completed!d!</title>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <link rel="preconnect" href="https://fonts.googleapis.com">
            <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
            <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@500&display=swap" rel="stylesheet">
            <style>
                body {
                    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
                    margin: 0; padding: 20px;
                    background: radial-gradient(circle at top left, #2c2e33 0%, #0f1012 100%);
                    color: #e1e1e1;
                    height: 100vh;
                    display: flex; align-items: center; justify-content: center;
                    box-sizing: border-box;
                    line-height: 1.6;
                    overflow: hidden;
                }
                
                @media (max-width: 550px) {
                    .card { width: 90%; padding: 30px; }
                }

                @media (max-height: 700px) {
                    .card { padding: 25px; }
                }
                
                .card {
                    background: rgba(30, 31, 34, 0.75);
                    backdrop-filter: blur(16px);
                    -webkit-backdrop-filter: blur(16px);
                    border: 1px solid rgba(255, 255, 255, 0.08);
                    padding: 40px; 
                    border-radius: 24px;
                    box-shadow: 0 20px 60px rgba(0,0,0,0.6);
                    width: 100%; 
                    max-width: 500px;
                    text-align: left;
                    position: relative;
                    
                }

                .card::before {
                    content: ''; position: absolute; top: 0; left: 0; right: 0; height: 1px;
                    background: linear-gradient(90deg, transparent, rgba(255,255,255,0.2), transparent);
                }
                
                .header-row { display: flex; align-items: center; gap: 12px; margin-bottom: 8px; }
                
                .success-icon { 
                    color: #43b581; 
                    width: 28px; height: 28px; 
                    animation: popIn 0.5s cubic-bezier(0.175, 0.885, 0.32, 1.275) forwards;
                }

                @keyframes popIn {
                    0% { transform: scale(0); opacity: 0; }
                    100% { transform: scale(1); opacity: 1; }
                }

                h1 { 
                    color: #ffffff; margin: 0;
                    font-size: 26px; font-weight: 800;
                    letter-spacing: -0.5px;
                }
                
                .subtitle { 
                    color: #b9bbbe; margin: 0;
                    font-size: 15px; font-weight: 400;
                }
                
                .highlight { color: #fff; font-weight: 600; }

                .divider {
                    height: 1px;
                    background: linear-gradient(90deg, rgba(255,255,255,0.0), rgba(255,255,255,0.1), rgba(255,255,255,0.0));
                    margin: 30px 0;
                }
                
                .section-title { 
                    margin: 0 0 15px 0; 
                    font-size: 12px; text-transform: uppercase; letter-spacing: 1px;
                    font-weight: 700; color: #949BA4;
                }
                
                .command-row {
                    display: flex; align-items: center; justify-content: space-between;
                    background: rgba(255,255,255,0.03);
                    border: 1px solid rgba(255,255,255,0.05);
                    padding: 12px 16px;
                    border-radius: 12px;
                    margin-bottom: 10px;
                    transition: background 0.2s;
                }
                
                .command-row:hover {
                    background: rgba(255,255,255,0.05);
                }

                .cmd-desc { font-size: 14px; color: #dbdee1; font-weight: 500; }

                code {
                    background: rgba(88, 101, 242, 0.15);
                    padding: 4px 8px; border-radius: 6px;
                    font-family: 'JetBrains Mono', monospace;
                    font-size: 13px; color: #8ea0e1;
                    border: 1px solid rgba(88, 101, 242, 0.2);
                }
                
                .status-badge {
                    display: inline-flex; align-items: center; gap: 8px;
                    font-size: 13px; color: #43b581;
                    background: rgba(67, 181, 129, 0.1);
                    padding: 8px 12px; border-radius: 20px;
                    margin-top: 10px; font-weight: 500;
                    border: 1px solid rgba(67, 181, 129, 0.1);
                }

                .footer-text {
                    margin-top: 32px; font-size: 13px; color: #82858f;
                    text-align: center;
                }
            </style>
        </head>
        <body>
            <div class="card">
                <div>
                    <div class="header-row">
                        <svg class="success-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>
                        <h1>Success!</h1>
                    </div>
                    <p class="subtitle"><strong>{{ guild_name }}</strong> is now connected to <span class="highlight">{{ github_org }}</span>.</p>
                </div>

                <div class="divider"></div>

                <div>
                    <h3 class="section-title">Next Steps in Discord</h3>
                    
                    <div class="command-row">
                        <span class="cmd-desc">1. Users link accounts</span>
                        <code>/link</code>
                    </div>

                    <div class="command-row">
                        <span class="cmd-desc">2. View stats</span>
                        <code>/getstats</code>
                    </div>

                    <div class="status-badge">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>
                        {% if sync_triggered %}
                        Data sync started. Stats appearing shortly.
                        {% else %}
                        Sync scheduled. Contributions ready soon.
                        {% endif %}
                    </div>
                </div>
                
                <p class="footer-text">
                    You can safely close this window and return to Discord.
                </p>
            </div>
        </body>
        </html>
        """

        return render_template_string(
            success_page,
            guild_name=guild_name,
            github_org=github_org,
            is_personal_install=is_personal_install,
            sync_triggered=sync_triggered
        )

    @app.route("/setup")
    def setup():
        """Setup page after Discord bot is added to server"""
        from flask import request, render_template_string
        from urllib.parse import urlencode

        # Get Discord server info from OAuth callback
        guild_id = request.args.get('guild_id')
        guild_name = request.args.get('guild_name', 'your server')

        if not guild_id:
            return "Error: No Discord server information received", 400

        github_app_install_url = f"{base_url}/github/app/install?{urlencode({'guild_id': guild_id, 'guild_name': guild_name})}"

        setup_page = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>DisgitBot Setup</title>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <link rel="preconnect" href="https://fonts.googleapis.com">
            <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
            <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@500&display=swap" rel="stylesheet">
            <style>
                body {
                    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
                    margin: 0; padding: 20px;
                    background: radial-gradient(circle at top left, #2c2e33 0%, #0f1012 100%);
                    color: #e1e1e1;
                    height: 100vh;
                    display: flex; align-items: center; justify-content: center;
                    box-sizing: border-box;
                    line-height: 1.6;
                    overflow: hidden;
                }

                @media (max-width: 550px) {
                    .card { width: 90%; padding: 30px; }
                }

                @media (max-height: 700px) {
                    .card { padding: 25px; }
                }
                
                .card {
                    background: rgba(30, 31, 34, 0.75);
                    backdrop-filter: blur(16px);
                    -webkit-backdrop-filter: blur(16px);
                    border: 1px solid rgba(255, 255, 255, 0.08);
                    padding: 40px; border-radius: 24px;
                    box-shadow: 0 20px 60px rgba(0,0,0,0.6);
                    width: 100%; max-width: 500px;
                    text-align: left;
                }
                
                h1 { 
                    color: #ffffff; margin: 0 0 8px 0; 
                    font-size: 24px; font-weight: 800;
                    letter-spacing: -0.5px;
                }
                
                .subtitle { 
                    color: #b9bbbe; margin: 0;
                    font-size: 15px; font-weight: 400;
                }
                
                .guild-name {
                    color: #fff;
                    font-weight: 600;
                }

                .divider {
                    height: 1px;
                    background: linear-gradient(90deg, rgba(255,255,255,0.0), rgba(255,255,255,0.1), rgba(255,255,255,0.0));
                    margin: 30px 0;
                }
                
                .section-title { 
                    margin: 0 0 10px 0; 
                    font-size: 18px; 
                    font-weight: 700; color: #ffffff;
                    display: flex; align-items: center; gap: 8px;
                }
                
                .section-desc {
                    color: #b9bbbe; margin-bottom: 25px;
                    font-size: 14px;
                }
                
                .btn {
                    background: linear-gradient(135deg, #5865f2 0%, #4752c4 100%);
                    color: white; padding: 12px 24px;
                    border: none; border-radius: 12px; font-weight: 600;
                    cursor: pointer; font-size: 15px; width: 100%;
                    transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
                    text-align: center; 
                    display: inline-flex; align-items: center; justify-content: center; gap: 10px;
                    text-decoration: none;
                    box-shadow: 0 4px 15px rgba(88, 101, 242, 0.2);
                    box-sizing: border-box;
                    position: relative; 
                }
                
                .btn::before {
                    content: '';
                    position: absolute;
                    top: 0; left: -100%; width: 100%; height: 100%;
                    background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.3), transparent);
                    transition: left 0.5s;
                }
                
                .btn:hover::before { left: 100%; }
                
                .btn:hover {
                    transform: translateY(-2px);
                    box-shadow: 0 8px 25px rgba(88, 101, 242, 0.3);
                    filter: brightness(1.1);
                }
                
                .github-icon { width: 20px; height: 20px; fill: currentColor; }
                
                .footer-text {
                    margin-top: 32px; font-size: 13px; color: #82858f;
                    text-align: center;
                }
                
                code {
                    background: rgba(255, 255, 255, 0.08);
                    padding: 2px 6px; border-radius: 4px;
                    font-family: 'JetBrains Mono', monospace;
                    font-size: 0.9em; color: #dcddde;
                    border: 1px solid rgba(255,255,255,0.1);
                }
            </style>
        </head>
        <body>
            <div class="card">
                <div>
                    <h1>DisgitBot Added!</h1>
                    <p class="subtitle">Bot has been successfully added to <span class="guild-name">{{ guild_name }}</span></p>
                </div>

                <div class="divider"></div>

                <div>
                    <h3 class="section-title">Install the GitHub App</h3>
                    <p class="section-desc">Required: Select which repositories you want the bot to track.</p>
                    
                    <a class="btn" href="{{ github_app_install_url }}">
                        <svg class="github-icon" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                            <path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z"/>
                        </svg>
                        Install GitHub App
                    </a>
                </div>
                
                <p class="footer-text">
                    After setup, users can link their GitHub accounts using <code>/link</code> in Discord.
                </p>
            </div>
        </body>
        </html>
        """

        return render_template_string(
            setup_page,
            guild_id=guild_id,
            guild_name=guild_name,
            github_app_install_url=github_app_install_url
        )
    
    @app.route("/complete_setup", methods=["POST"])
    def complete_setup():
        """Complete the setup process"""
        from flask import request, render_template_string
        from shared.firestore import get_mt_client
        from datetime import datetime
        
        guild_id = request.form.get('guild_id')
        selected_org = request.form.get('github_org', '').strip()
        manual_org = request.form.get('manual_org', '').strip()
        github_org = manual_org or selected_org
        setup_source = request.form.get('setup_source', 'manual').strip() or 'manual'
        
        if not guild_id or not github_org:
            return "Error: Missing required information", 400
        
        # Validate GitHub organization name (basic validation)
        if not github_org.replace('-', '').replace('_', '').isalnum():
            return "Error: Invalid GitHub organization name", 400
        
        try:
            # Store server configuration
            mt_client = get_mt_client()
            success = mt_client.set_server_config(guild_id, {
                'github_org': github_org,
                'setup_source': setup_source,
                'created_at': datetime.now().isoformat(),
                'setup_completed': True
            })
            
            if not success:
                return "Error: Failed to save configuration", 500
            
            
            success_page = """
            <!DOCTYPE html>
            <html>
            <head>
                <title>Setup Completed!d!</title>
                <meta charset="utf-8">
                <meta name="viewport" content="width=device-width, initial-scale=1">
                <link rel="preconnect" href="https://fonts.googleapis.com">
                <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
                <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@500&display=swap" rel="stylesheet">
                <style>
                    body {
                        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
                        margin: 0; padding: 20px;
                        background: radial-gradient(circle at top left, #2c2e33 0%, #0f1012 100%);
                        color: #e1e1e1;
                        height: 100vh;
                        display: flex; align-items: center; justify-content: center;
                        box-sizing: border-box;
                        line-height: 1.6;
                        overflow: hidden;
                    }

                    @media (max-width: 550px) {
                        .card { width: 90%; padding: 30px; }
                        h1 { font-size: 22px; }
                    }

                    @media (max-height: 700px) {
                        .card { padding: 25px; }
                        .divider { margin: 20px 0; }
                    }
                    
                    .card {
                        background: rgba(30, 31, 34, 0.75);
                        backdrop-filter: blur(16px);
                        -webkit-backdrop-filter: blur(16px);
                        border: 1px solid rgba(255, 255, 255, 0.08);
                        padding: 40px; 
                        border-radius: 24px;
                        box-shadow: 0 20px 60px rgba(0,0,0,0.6);
                        width: 100%; 
                        max-width: 500px;
                        text-align: left;
                        position: relative;
                        
                    }

                    .card::before {
                        content: ''; position: absolute; top: 0; left: 0; right: 0; height: 1px;
                        background: linear-gradient(90deg, transparent, rgba(255,255,255,0.2), transparent);
                    }
                    
                    .header-row { display: flex; align-items: center; gap: 12px; margin-bottom: 8px; }
                    
                    .success-icon { 
                        color: #43b581; 
                        width: 28px; height: 28px; 
                        animation: popIn 0.5s cubic-bezier(0.175, 0.885, 0.32, 1.275) forwards;
                    }

                    @keyframes popIn {
                        0% { transform: scale(0); opacity: 0; }
                        100% { transform: scale(1); opacity: 1; }
                    }

                    h1 { 
                        color: #ffffff; margin: 0;
                        font-size: 26px; font-weight: 800;
                        letter-spacing: -0.5px;
                    }
                    
                    .subtitle { 
                        color: #b9bbbe; margin: 0;
                        font-size: 15px; font-weight: 400;
                    }
                    
                    .highlight { color: #fff; font-weight: 600; }

                    .divider {
                        height: 1px;
                        background: linear-gradient(90deg, rgba(255,255,255,0.0), rgba(255,255,255,0.1), rgba(255,255,255,0.0));
                        margin: 30px 0;
                    }
                    
                    .section-title { 
                        margin: 0 0 15px 0; 
                        font-size: 12px; text-transform: uppercase; letter-spacing: 1px;
                        font-weight: 700; color: #949BA4;
                    }
                    
                    .command-row {
                        display: flex; align-items: center; justify-content: space-between;
                        background: rgba(255,255,255,0.03);
                        border: 1px solid rgba(255,255,255,0.05);
                        padding: 12px 16px;
                        border-radius: 12px;
                        margin-bottom: 10px;
                        transition: background 0.2s;
                    }
                    
                    .command-row:hover {
                        background: rgba(255,255,255,0.05);
                    }

                    .cmd-desc { font-size: 14px; color: #dbdee1; font-weight: 500; }

                    code {
                        background: rgba(88, 101, 242, 0.15);
                        padding: 4px 8px; border-radius: 6px;
                        font-family: 'JetBrains Mono', monospace;
                        font-size: 13px; color: #8ea0e1;
                        border: 1px solid rgba(88, 101, 242, 0.2);
                    }
                    
                    .status-badge {
                        display: inline-flex; align-items: center; gap: 8px;
                        font-size: 13px; color: #43b581;
                        background: rgba(67, 181, 129, 0.1);
                        padding: 8px 12px; border-radius: 20px;
                        margin-top: 10px; font-weight: 500;
                        border: 1px solid rgba(67, 181, 129, 0.1);
                    }

                    .footer-text {
                        margin-top: 32px; font-size: 13px; color: #82858f;
                        text-align: center;
                    }
                </style>
            </head>
            <body>
                <div class="card">
                    <div>
                        <div class="header-row">
                            <svg class="success-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>
                            <h1>Success!</h1>
                        </div>
                        <p class="subtitle"><strong>{{ guild_name }}</strong> is now connected to <span class="highlight">{{ github_org }}</span>.</p>
                    </div>

                    <div class="divider"></div>

                    <div>
                        <h3 class="section-title">Next Steps in Discord</h3>
                        
                        <div class="command-row">
                            <span class="cmd-desc">1. Users link accounts</span>
                            <code>/link</code>
                        </div>

                        <div class="command-row">
                            <span class="cmd-desc">2. View stats</span>
                            <code>/getstats</code>
                        </div>

                        <div class="status-badge">
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>
                            Data sync started. Stats appearing shortly.
                        </div>
                    </div>
                    
                    <p class="footer-text">
                        You can safely close this window and return to Discord.
                    </p>
                </div>
            </body>
            </html>
            """
            
            return render_template_string(success_page, github_org=github_org)
            
        except Exception as e:
            print(f"Error in complete_setup: {e}")
            return f"Error: Setup failed - {str(e)}", 500
    
    return app

def get_github_username_for_user(discord_user_id):
    """Get OAuth URL for a specific Discord user"""
    base_url = os.getenv("OAUTH_BASE_URL")
    if not base_url:
        raise ValueError("OAUTH_BASE_URL environment variable is required")
    
    return f"{base_url}/auth/start/{discord_user_id}"

def wait_for_username(discord_user_id, max_wait_time=300):
    """Wait for OAuth completion by polling the status"""
    start_time = time.time()
    
    while time.time() - start_time < max_wait_time:
        with oauth_sessions_lock:
            session_data = oauth_sessions.get(discord_user_id)
            
            if session_data:
                if session_data['status'] == 'completed':
                    github_username = session_data.get('github_username')
                    # Clean up
                    del oauth_sessions[discord_user_id]
                    return github_username
                elif session_data['status'] == 'failed':
                    error = session_data.get('error', 'Unknown error')
                    print(f"OAuth failed for {discord_user_id}: {error}")
                    # Clean up
                    del oauth_sessions[discord_user_id]
                    return None
        
        time.sleep(2)  # Poll every 2 seconds
    
    print(f"OAuth timeout for Discord user: {discord_user_id}")
    # Clean up timeout session
    with oauth_sessions_lock:
        if discord_user_id in oauth_sessions:
            del oauth_sessions[discord_user_id]
    
    return None

#!/usr/bin/env python3
"""
Discord Bot Setup Wizard
Automated deployment setup for Discord bot component only
"""

import os
import sys
import json
import subprocess
import secrets
import string
import requests
from pathlib import Path
from typing import Dict, Optional, Tuple
import tempfile
import base64

class Color:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'

class DiscordBotSetupWizard:
    def __init__(self):
        self.config = {}
        self.discord_bot_root = Path(__file__).parent.parent
        self.setup_dir = self.discord_bot_root / "automation" / "generated"
        self.setup_dir.mkdir(exist_ok=True)
        
    def print_header(self):
        print(f"{Color.HEADER}{Color.BOLD}")
        print("=" * 60)
        print("     DISCORD BOT AUTOMATED SETUP WIZARD")
        print("=" * 60)
        print(f"{Color.ENDC}")
        print(f"{Color.CYAN}Deploy Discord Bot with GitHub integration{Color.ENDC}")
        print(f"{Color.CYAN}Automated setup in under 5 minutes{Color.ENDC}")
        print(f"{Color.WARNING}Note: This deploys ONLY the Discord bot component{Color.ENDC}")
        print(f"{Color.WARNING}PR review runs separately via GitHub Actions{Color.ENDC}\n")
        
    def collect_user_inputs(self) -> Dict[str, str]:
        """Collect minimal required information from user"""
        print(f"{Color.BOLD}STEP 1: Basic Information{Color.ENDC}")
        print("We need just a few details to get started:\n")
        
        inputs = {}
        
        # Organization name
        inputs['org_name'] = input(f"{Color.BLUE}GitHub organization name: {Color.ENDC}").strip()
        if not inputs['org_name']:
            print(f"{Color.FAIL}Organization name is required{Color.ENDC}")
            sys.exit(1)
            
        # Discord bot token
        print(f"\n{Color.WARNING}You need to create a Discord application first:{Color.ENDC}")
        print("1. Go to https://discord.com/developers/applications")
        print("2. Click 'New Application' and give it a name")
        print("3. Go to 'Bot' tab and copy the token")
        inputs['discord_token'] = input(f"\n{Color.BLUE}Discord bot token: {Color.ENDC}").strip()
        if not inputs['discord_token']:
            print(f"{Color.FAIL}Discord bot token is required{Color.ENDC}")
            sys.exit(1)
            
        # GitHub token
        print(f"\n{Color.WARNING}Create a GitHub personal access token:{Color.ENDC}")
        print("1. Go to https://github.com/settings/tokens")
        print("2. Click 'Generate new token (classic)'")
        print("3. Select 'repo' scope")
        inputs['github_token'] = input(f"\n{Color.BLUE}GitHub token: {Color.ENDC}").strip()
        if not inputs['github_token']:
            print(f"{Color.FAIL}GitHub token is required{Color.ENDC}")
            sys.exit(1)
            
        # Google Cloud project (optional - we can create one)
        inputs['gcp_project'] = input(f"{Color.BLUE}Google Cloud project ID (leave empty to create new): {Color.ENDC}").strip()
        
        return inputs
        
    def setup_google_cloud(self, project_id: Optional[str] = None) -> Tuple[str, str]:
        """Setup Google Cloud infrastructure for Discord bot"""
        print(f"\n{Color.BOLD}STEP 2: Google Cloud Setup{Color.ENDC}")
        
        if not project_id:
            project_id = f"discord-bot-{secrets.token_hex(8)}"
            print(f"Creating new Google Cloud project: {project_id}")
            
            try:
                subprocess.run(["gcloud", "projects", "create", project_id, 
                              "--name=Discord Bot"], check=True, capture_output=True)
                print(f"{Color.GREEN}✓ Project created successfully{Color.ENDC}")
            except subprocess.CalledProcessError as e:
                print(f"{Color.FAIL}Failed to create project: {e}{Color.ENDC}")
                sys.exit(1)
        else:
            print(f"Using existing Google Cloud project: {project_id}")
            # Check if project exists
            try:
                result = subprocess.run(["gcloud", "projects", "describe", project_id], 
                                      check=True, capture_output=True, text=True)
                print(f"{Color.GREEN}✓ Project exists and accessible{Color.ENDC}")
            except subprocess.CalledProcessError:
                print(f"{Color.FAIL}Project {project_id} not found or not accessible{Color.ENDC}")
                print(f"{Color.WARNING}Make sure you have access and the project exists{Color.ENDC}")
                sys.exit(1)
        
        subprocess.run(["gcloud", "config", "set", "project", project_id], check=True)
        
        # Enable required APIs for Discord bot only
        apis = [
            "run.googleapis.com",
            "cloudbuild.googleapis.com",
            "firestore.googleapis.com"
        ]
        
        print("Enabling required APIs...")
        for api in apis:
            try:
                subprocess.run(["gcloud", "services", "enable", api], 
                             check=True, capture_output=True)
                print(f"{Color.GREEN}✓ {api} enabled{Color.ENDC}")
            except subprocess.CalledProcessError:
                print(f"{Color.WARNING}Warning: Could not enable {api}{Color.ENDC}")
        
        # Create Firestore database
        print("Setting up Firestore...")
        try:
            subprocess.run(["gcloud", "firestore", "databases", "create", 
                          "--region=us-central"], check=True, capture_output=True)
            print(f"{Color.GREEN}✓ Firestore database created{Color.ENDC}")
        except subprocess.CalledProcessError:
            print(f"{Color.WARNING}Firestore database may already exist{Color.ENDC}")
        
        # Create service account and key
        service_account = f"discord-bot-sa@{project_id}.iam.gserviceaccount.com"
        key_file = self.setup_dir / "service-account-key.json"
        
        try:
            subprocess.run([
                "gcloud", "iam", "service-accounts", "create", "discord-bot-sa",
                "--display-name=Discord Bot Service Account"
            ], check=True, capture_output=True)
            
            subprocess.run([
                "gcloud", "projects", "add-iam-policy-binding", project_id,
                "--member", f"serviceAccount:{service_account}",
                "--role", "roles/datastore.user"
            ], check=True, capture_output=True)
            
            subprocess.run([
                "gcloud", "iam", "service-accounts", "keys", "create", 
                str(key_file),
                "--iam-account", service_account
            ], check=True, capture_output=True)
            
            print(f"{Color.GREEN}✓ Service account created and key downloaded{Color.ENDC}")
            
        except subprocess.CalledProcessError as e:
            print(f"{Color.FAIL}Service account setup failed: {e}{Color.ENDC}")
            sys.exit(1)
            
        return project_id, str(key_file)
    
    def deploy_discord_bot(self, project_id: str, service_key_path: str) -> str:
        """Deploy Discord bot to Cloud Run and return URL"""
        print(f"\n{Color.BOLD}STEP 3: Discord Bot Deployment{Color.ENDC}")
        
        try:
            print("Building Discord bot container...")
            subprocess.run([
                "gcloud", "builds", "submit",
                "--tag", f"gcr.io/{project_id}/discord-bot",
                str(self.discord_bot_root)
            ], check=True)
            
            print("Deploying Discord bot to Cloud Run...")
            result = subprocess.run([
                "gcloud", "run", "deploy", "discord-bot",
                "--image", f"gcr.io/{project_id}/discord-bot",
                "--platform", "managed",
                "--region", "us-central1",
                "--allow-unauthenticated",
                "--port", "8080",
                "--memory", "1Gi"
            ], capture_output=True, text=True, check=True)
            
            url_result = subprocess.run([
                "gcloud", "run", "services", "describe", "discord-bot",
                "--region", "us-central1",
                "--format", "value(status.url)"
            ], capture_output=True, text=True, check=True)
            
            service_url = url_result.stdout.strip()
            print(f"{Color.GREEN}✓ Discord bot deployed to: {service_url}{Color.ENDC}")
            return service_url
            
        except subprocess.CalledProcessError as e:
            print(f"{Color.FAIL}Deployment failed: {e}{Color.ENDC}")
            sys.exit(1)
    
    def setup_github_oauth(self, service_url: str) -> Tuple[str, str]:
        """Create GitHub OAuth app for Discord bot authentication"""
        print(f"\n{Color.BOLD}STEP 4: GitHub OAuth Setup{Color.ENDC}")
        print(f"{Color.WARNING}Manual step required:{Color.ENDC}")
        print("1. Go to https://github.com/settings/developers")
        print("2. Click 'New OAuth App'")
        print("3. Use these settings:")
        print(f"   - Application name: Discord Bot for {self.config['org_name']}")
        print(f"   - Homepage URL: {service_url}")
        print(f"   - Authorization callback URL: {service_url}/auth/callback")
        
        client_id = input(f"\n{Color.BLUE}OAuth Client ID: {Color.ENDC}").strip()
        client_secret = input(f"{Color.BLUE}OAuth Client Secret: {Color.ENDC}").strip()
        
        if not client_id or not client_secret:
            print(f"{Color.FAIL}OAuth credentials are required{Color.ENDC}")
            sys.exit(1)
            
        return client_id, client_secret
    
    def generate_configuration_files(self, project_id: str, service_url: str, 
                                   oauth_client_id: str, oauth_client_secret: str):
        """Generate Discord bot configuration files"""
        print(f"\n{Color.BOLD}STEP 5: Configuration Generation{Color.ENDC}")
        
        # Generate .env file for Discord bot
        env_content = f"""DISCORD_BOT_TOKEN={self.config['discord_token']}
GITHUB_TOKEN={self.config['github_token']}
GITHUB_CLIENT_ID={oauth_client_id}
GITHUB_CLIENT_SECRET={oauth_client_secret}
REPO_OWNER={self.config['org_name']}
OAUTH_BASE_URL={service_url}
GOOGLE_APPLICATION_CREDENTIALS=/app/config/credentials.json
"""
        
        env_file = self.discord_bot_root / "config" / ".env"
        env_file.write_text(env_content)
        print(f"{Color.GREEN}✓ Generated Discord bot .env file{Color.ENDC}")
        
        # Generate GitHub Actions secrets setup script
        secrets_script = f"""#!/bin/bash
# GitHub Repository Secrets Setup for Discord Bot
# Run this in your repository directory

gh secret set DISCORD_BOT_TOKEN --body "{self.config['discord_token']}"
gh secret set DEV_GH_TOKEN --body "{self.config['github_token']}"
gh secret set GOOGLE_CREDENTIALS_JSON --body "$(cat {self.setup_dir}/service-account-key.json | base64 -w 0)"
gh secret set REPO_OWNER --body "{self.config['org_name']}"
gh secret set CLOUD_RUN_URL --body "{service_url}"
gh secret set GCP_PROJECT_ID --body "{project_id}"

echo "Discord Bot secrets configured successfully!"
"""
        
        secrets_file = self.setup_dir / "setup_github_secrets.sh"
        secrets_file.write_text(secrets_script)
        secrets_file.chmod(0o755)
        print(f"{Color.GREEN}✓ Generated GitHub secrets setup script{Color.ENDC}")
        
        # Generate deployment summary
        summary = f"""
DISCORD BOT DEPLOYMENT SUMMARY
==============================

Component: Discord Bot Only
Project ID: {project_id}
Service URL: {service_url}
Organization: {self.config['org_name']}

WHAT WAS DEPLOYED:
- Discord bot with GitHub OAuth integration
- Real-time contribution statistics
- Automated role management
- Voice channel metrics display

WHAT RUNS SEPARATELY:
- PR review automation (runs via GitHub Actions)
- AI-powered labeling (triggered by PR events)
- Reviewer assignment (GitHub Actions workflow)

NEXT STEPS:
1. Run the GitHub secrets script: ./discord_bot/automation/generated/setup_github_secrets.sh
2. Invite the bot to your Discord server with admin permissions
3. Test the setup with /link command

FILES CREATED:
- discord_bot/config/.env (Discord bot environment variables)
- discord_bot/automation/generated/setup_github_secrets.sh (GitHub configuration)
- discord_bot/automation/generated/service-account-key.json (Google Cloud credentials)

SUPPORT:
- Documentation: ../README.md
- Issues: https://github.com/ruxailab/disgitbot/issues
"""
        
        summary_file = self.setup_dir / "deployment_summary.txt"
        summary_file.write_text(summary)
        print(f"{Color.GREEN}✓ Generated deployment summary{Color.ENDC}")
        
    def run_setup(self):
        """Execute complete Discord bot setup process"""
        try:
            self.print_header()
            
            # Collect inputs
            self.config = self.collect_user_inputs()
            
            # Setup Google Cloud
            project_id, key_file = self.setup_google_cloud(self.config.get('gcp_project'))
            
            # Deploy Discord bot
            service_url = self.deploy_discord_bot(project_id, key_file)
            
            # Setup OAuth
            oauth_client_id, oauth_client_secret = self.setup_github_oauth(service_url)
            
            # Generate config files
            self.generate_configuration_files(project_id, service_url, oauth_client_id, oauth_client_secret)
            
            print(f"\n{Color.GREEN}{Color.BOLD}🎉 DISCORD BOT SETUP COMPLETE! 🎉{Color.ENDC}")
            print(f"{Color.CYAN}Your Discord Bot is deployed and ready to use!{Color.ENDC}")
            print(f"\nNext: Run {Color.BOLD}./discord_bot/automation/generated/setup_github_secrets.sh{Color.ENDC}")
            
        except KeyboardInterrupt:
            print(f"\n{Color.WARNING}Setup cancelled by user{Color.ENDC}")
            sys.exit(1)
        except Exception as e:
            print(f"\n{Color.FAIL}Setup failed: {e}{Color.ENDC}")
            sys.exit(1)

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--help":
        print("Discord Bot Setup Wizard")
        print("Automated deployment for Discord bot component only")
        print("\nUsage: python3 setup_wizard.py")
        print("\nRequirements:")
        print("- Google Cloud SDK (gcloud) installed and authenticated")
        print("- GitHub CLI (gh) installed and authenticated")
        print("- Docker installed")
        print("\nNote: This deploys ONLY the Discord bot. PR review runs via GitHub Actions.")
        sys.exit(0)
        
    wizard = DiscordBotSetupWizard()
    wizard.run_setup()
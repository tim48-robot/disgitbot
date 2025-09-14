#!/usr/bin/env python3
"""
GitHub Actions Workflow Generator for Discord Bot
Generates customized workflows focused on Discord bot deployment
"""

import yaml
from pathlib import Path
from typing import Dict

class DiscordBotWorkflowGenerator:
    def __init__(self, org_name: str, repo_name: str = None):
        self.org_name = org_name
        self.repo_name = repo_name or "disgitbot"
        self.workflows_dir = Path(".github/workflows")
        self.workflows_dir.mkdir(parents=True, exist_ok=True)
    
    def generate_discord_bot_pipeline_workflow(self) -> str:
        """Generate the Discord bot data collection pipeline workflow"""
        workflow = {
            'name': f'{self.org_name} Discord Bot Pipeline',
            'on': {
                'schedule': [{'cron': '0 0 * * *'}],  # Daily at midnight UTC
                'workflow_dispatch': {},  # Manual trigger
                'push': {
                    'branches': ['main'],
                    'paths': ['discord_bot/**']
                }
            },
            'jobs': {
                'discord-bot-pipeline': {
                    'runs-on': 'ubuntu-latest',
                    'steps': [
                        {
                            'name': 'Checkout repository',
                            'uses': 'actions/checkout@v4'
                        },
                        {
                            'name': 'Set up Python 3.13',
                            'uses': 'actions/setup-python@v5',
                            'with': {
                                'python-version': '3.13',
                                'cache': 'pip',
                                'cache-dependency-path': 'discord_bot/requirements.txt'
                            }
                        },
                        {
                            'name': 'Install system dependencies',
                            'run': 'sudo apt-get update && sudo apt-get install -y libffi-dev libnacl-dev python3-dev build-essential'
                        },
                        {
                            'name': 'Install Python dependencies',
                            'run': 'python -m pip install --upgrade pip wheel setuptools && pip install -r discord_bot/requirements.txt'
                        },
                        {
                            'name': 'Set up Google Credentials',
                            'run': 'echo "${{ secrets.GOOGLE_CREDENTIALS_JSON }}" | base64 --decode > discord_bot/config/credentials.json'
                        },
                        {
                            'name': 'Collect GitHub Data',
                            'env': {
                                'GITHUB_TOKEN': '${{ secrets.DEV_GH_TOKEN }}',
                                'REPO_OWNER': '${{ secrets.REPO_OWNER }}',
                                'PYTHONUNBUFFERED': '1'
                            },
                            'run': 'cd discord_bot && python -m src.services.github_service'
                        },
                        {
                            'name': 'Process Contributions',
                            'env': {
                                'GITHUB_TOKEN': '${{ secrets.DEV_GH_TOKEN }}',
                                'REPO_OWNER': '${{ secrets.REPO_OWNER }}',
                                'PYTHONUNBUFFERED': '1'
                            },
                            'run': 'cd discord_bot && python -m src.pipeline.processors.contribution_processor'
                        },
                        {
                            'name': 'Generate Analytics',
                            'env': {
                                'GITHUB_TOKEN': '${{ secrets.DEV_GH_TOKEN }}',
                                'REPO_OWNER': '${{ secrets.REPO_OWNER }}',
                                'PYTHONUNBUFFERED': '1'
                            },
                            'run': 'cd discord_bot && python -m src.pipeline.processors.analytics_processor'
                        },
                        {
                            'name': 'Update Discord Roles',
                            'env': {
                                'DISCORD_BOT_TOKEN': '${{ secrets.DISCORD_BOT_TOKEN }}',
                                'GITHUB_TOKEN': '${{ secrets.DEV_GH_TOKEN }}',
                                'REPO_OWNER': '${{ secrets.REPO_OWNER }}',
                                'PYTHONUNBUFFERED': '1'
                            },
                            'run': 'cd discord_bot && python -m src.services.guild_service'
                        }
                    ]
                }
            }
        }
        
        workflow_file = self.workflows_dir / f'{self.org_name.lower()}-discord-bot-pipeline.yml'
        with open(workflow_file, 'w') as f:
            yaml.dump(workflow, f, default_flow_style=False, sort_keys=False)
        
        return str(workflow_file)
    
    def generate_discord_bot_deployment_workflow(self) -> str:
        """Generate Discord bot Cloud Run deployment workflow"""
        workflow = {
            'name': f'{self.org_name} Discord Bot Deploy',
            'on': {
                'push': {
                    'branches': ['main'],
                    'paths': ['discord_bot/**']
                },
                'workflow_dispatch': {}
            },
            'jobs': {
                'deploy-discord-bot': {
                    'runs-on': 'ubuntu-latest',
                    'steps': [
                        {
                            'name': 'Checkout code',
                            'uses': 'actions/checkout@v4'
                        },
                        {
                            'name': 'Set up Cloud SDK',
                            'uses': 'google-github-actions/setup-gcloud@v2',
                            'with': {
                                'service_account_key': '${{ secrets.GOOGLE_CREDENTIALS_JSON }}',
                                'project_id': '${{ secrets.GCP_PROJECT_ID }}'
                            }
                        },
                        {
                            'name': 'Configure Docker for GCR',
                            'run': 'gcloud auth configure-docker'
                        },
                        {
                            'name': 'Build and Deploy Discord Bot',
                            'env': {
                                'DISCORD_BOT_TOKEN': '${{ secrets.DISCORD_BOT_TOKEN }}',
                                'GITHUB_TOKEN': '${{ secrets.DEV_GH_TOKEN }}',
                                'REPO_OWNER': '${{ secrets.REPO_OWNER }}'
                            },
                            'run': '''
                            cd discord_bot
                            gcloud builds submit --tag gcr.io/${{ secrets.GCP_PROJECT_ID }}/discord-bot
                            gcloud run deploy discord-bot \\
                              --image gcr.io/${{ secrets.GCP_PROJECT_ID }}/discord-bot \\
                              --platform managed \\
                              --region us-central1 \\
                              --allow-unauthenticated \\
                              --port 8080 \\
                              --memory 1Gi \\
                              --set-env-vars DISCORD_BOT_TOKEN="${{ secrets.DISCORD_BOT_TOKEN }}" \\
                              --set-env-vars GITHUB_TOKEN="${{ secrets.DEV_GH_TOKEN }}" \\
                              --set-env-vars REPO_OWNER="${{ secrets.REPO_OWNER }}" \\
                              --set-env-vars OAUTH_BASE_URL="${{ secrets.CLOUD_RUN_URL }}"
                            '''
                        }
                    ]
                }
            }
        }
        
        workflow_file = self.workflows_dir / f'{self.org_name.lower()}-discord-bot-deploy.yml'
        with open(workflow_file, 'w') as f:
            yaml.dump(workflow, f, default_flow_style=False, sort_keys=False)
            
        return str(workflow_file)
    
    def generate_discord_bot_health_check_workflow(self) -> str:
        """Generate Discord bot health monitoring workflow"""
        workflow = {
            'name': f'{self.org_name} Discord Bot Health Check',
            'on': {
                'schedule': [{'cron': '*/30 * * * *'}],  # Every 30 minutes
                'workflow_dispatch': {}
            },
            'jobs': {
                'health-check-discord-bot': {
                    'runs-on': 'ubuntu-latest',
                    'steps': [
                        {
                            'name': 'Check Discord Bot Status',
                            'run': '''
                            response=$(curl -s -o /dev/null -w "%{http_code}" ${{ secrets.CLOUD_RUN_URL }})
                            if [ $response -eq 200 ]; then
                              echo "✅ Discord Bot is healthy"
                            else
                              echo "❌ Discord Bot health check failed (HTTP $response)"
                              exit 1
                            fi
                            '''
                        },
                        {
                            'name': 'Discord Notification on Failure',
                            'if': 'failure()',
                            'run': '''
                            curl -X POST "${{ secrets.DISCORD_WEBHOOK_URL }}" \\
                              -H "Content-Type: application/json" \\
                              -d '{
                                "content": "🚨 Discord Bot health check failed for ${{ github.repository }}",
                                "embeds": [{
                                  "title": "Discord Bot Service Alert",
                                  "description": "The Discord Bot service appears to be down. Please check the Cloud Run logs.",
                                  "color": 15158332,
                                  "timestamp": "'$(date -u +%Y-%m-%dT%H:%M:%S.%3NZ)'"
                                }]
                              }'
                            '''
                        }
                    ]
                }
            }
        }
        
        workflow_file = self.workflows_dir / f'{self.org_name.lower()}-discord-bot-health.yml'
        with open(workflow_file, 'w') as f:
            yaml.dump(workflow, f, default_flow_style=False, sort_keys=False)
            
        return str(workflow_file)
    
    def generate_discord_bot_workflows(self) -> Dict[str, str]:
        """Generate Discord bot workflow files and return file paths"""
        workflows = {
            'discord_bot_pipeline': self.generate_discord_bot_pipeline_workflow(),
            'discord_bot_deployment': self.generate_discord_bot_deployment_workflow(),
            'discord_bot_health_check': self.generate_discord_bot_health_check_workflow()
        }
        
        print(f"Generated {len(workflows)} Discord Bot GitHub Actions workflows:")
        for name, path in workflows.items():
            print(f"  - {name}: {path}")
            
        return workflows

def main():
    import sys
    if len(sys.argv) < 2:
        print("Usage: python workflow_generator.py <organization_name> [repo_name]")
        sys.exit(1)
    
    org_name = sys.argv[1]
    repo_name = sys.argv[2] if len(sys.argv) > 2 else None
    
    generator = DiscordBotWorkflowGenerator(org_name, repo_name)
    generator.generate_discord_bot_workflows()
    
    print(f"\n✅ Discord Bot workflows generated for {org_name}")
    print("Next steps:")
    print("1. Commit and push these workflow files")
    print("2. Configure the required repository secrets")
    print("3. Workflows will run automatically based on their triggers")

if __name__ == "__main__":
    main()
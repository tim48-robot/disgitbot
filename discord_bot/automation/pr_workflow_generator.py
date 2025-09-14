#!/usr/bin/env python3
"""
PR Review Automation Workflow Generator
Generates workflows specifically for the separate PR review component
"""

import yaml
from pathlib import Path
from typing import Dict

class PRAutomationWorkflowGenerator:
    def __init__(self, org_name: str):
        self.org_name = org_name
        self.workflows_dir = Path(".github/workflows")
        self.workflows_dir.mkdir(parents=True, exist_ok=True)
    
    def generate_pr_automation_workflow(self) -> str:
        """Generate PR automation workflow for the separate pr_review component"""
        workflow = {
            'name': f'{self.org_name} PR Automation',
            'on': {
                'pull_request': {
                    'types': ['opened', 'synchronize', 'reopened']
                }
            },
            'jobs': {
                'pr-automation': {
                    'runs-on': 'ubuntu-latest',
                    'permissions': {
                        'contents': 'read',
                        'pull-requests': 'write',
                        'issues': 'write'
                    },
                    'steps': [
                        {
                            'name': 'Checkout code',
                            'uses': 'actions/checkout@v4'
                        },
                        {
                            'name': 'Set up Python 3.13',
                            'uses': 'actions/setup-python@v5',
                            'with': {
                                'python-version': '3.13'
                            }
                        },
                        {
                            'name': 'Install PR Review dependencies',
                            'run': 'pip install -r pr_review/requirements.txt'
                        },
                        {
                            'name': 'Set up Google Credentials for PR Review',
                            'run': 'echo "${{ secrets.GOOGLE_CREDENTIALS_JSON }}" | base64 --decode > pr_review/config/credentials.json'
                        },
                        {
                            'name': 'Run PR Automation',
                            'env': {
                                'GITHUB_TOKEN': '${{ secrets.GITHUB_TOKEN }}',
                                'GOOGLE_APPLICATION_CREDENTIALS': 'pr_review/config/credentials.json',
                                'REPO_OWNER': '${{ secrets.REPO_OWNER }}',
                                'PR_NUMBER': '${{ github.event.pull_request.number }}',
                                'REPO_NAME': '${{ github.repository }}'
                            },
                            'run': 'cd pr_review && python main.py'
                        }
                    ]
                }
            }
        }
        
        workflow_file = self.workflows_dir / f'{self.org_name.lower()}-pr-automation.yml'
        with open(workflow_file, 'w') as f:
            yaml.dump(workflow, f, default_flow_style=False, sort_keys=False)
            
        return str(workflow_file)
    
    def generate_pr_labeler_workflow(self) -> str:
        """Generate AI-powered PR labeling workflow"""
        workflow = {
            'name': f'{self.org_name} AI PR Labeler',
            'on': {
                'pull_request': {
                    'types': ['opened', 'reopened', 'edited']
                }
            },
            'jobs': {
                'ai-pr-labeler': {
                    'runs-on': 'ubuntu-latest',
                    'permissions': {
                        'contents': 'read',
                        'pull-requests': 'write'
                    },
                    'steps': [
                        {
                            'name': 'Checkout code',
                            'uses': 'actions/checkout@v4'
                        },
                        {
                            'name': 'Set up Python 3.13',
                            'uses': 'actions/setup-python@v5',
                            'with': {
                                'python-version': '3.13'
                            }
                        },
                        {
                            'name': 'Install dependencies',
                            'run': 'pip install -r pr_review/requirements.txt'
                        },
                        {
                            'name': 'Set up Google Credentials',
                            'run': 'echo "${{ secrets.GOOGLE_CREDENTIALS_JSON }}" | base64 --decode > pr_review/config/credentials.json'
                        },
                        {
                            'name': 'Run AI PR Labeling',
                            'env': {
                                'GITHUB_TOKEN': '${{ secrets.GITHUB_TOKEN }}',
                                'GOOGLE_APPLICATION_CREDENTIALS': 'pr_review/config/credentials.json',
                                'PR_NUMBER': '${{ github.event.pull_request.number }}',
                                'REPO_NAME': '${{ github.repository }}'
                            },
                            'run': 'cd pr_review && python -c "from utils.ai_pr_labeler import AIPRLabeler; labeler = AIPRLabeler(); labeler.process_pr()"'
                        }
                    ]
                }
            }
        }
        
        workflow_file = self.workflows_dir / f'{self.org_name.lower()}-ai-pr-labeler.yml'
        with open(workflow_file, 'w') as f:
            yaml.dump(workflow, f, default_flow_style=False, sort_keys=False)
            
        return str(workflow_file)
    
    def generate_pr_workflows(self) -> Dict[str, str]:
        """Generate all PR-related workflow files"""
        workflows = {
            'pr_automation': self.generate_pr_automation_workflow(),
            'ai_pr_labeler': self.generate_pr_labeler_workflow()
        }
        
        print(f"Generated {len(workflows)} PR automation workflows:")
        for name, path in workflows.items():
            print(f"  - {name}: {path}")
            
        return workflows

def main():
    import sys
    if len(sys.argv) < 2:
        print("Usage: python pr_workflow_generator.py <organization_name>")
        sys.exit(1)
    
    org_name = sys.argv[1]
    generator = PRAutomationWorkflowGenerator(org_name)
    generator.generate_pr_workflows()
    
    print(f"\n✅ PR automation workflows generated for {org_name}")
    print("Note: These workflows are for the separate pr_review component")

if __name__ == "__main__":
    main()
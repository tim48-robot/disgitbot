# Maintainer Guide

This document explains how to manage the environment variables and how to re-enable features that are currently disabled (commented out) on the `feature/saas-ready` branch.

## Environment Variables

### Core Variables (Required for Launch)
These are already in your `.env.example`:
- `DISCORD_BOT_TOKEN`: The bot token from Discord Developer Portal.
- `DISCORD_BOT_CLIENT_ID`: The client ID of your Discord bot.
- `GITHUB_CLIENT_ID`: OAuth client ID from your GitHub App.
- `GITHUB_CLIENT_SECRET`: OAuth client secret from your GitHub App.
- `OAUTH_BASE_URL`: The public URL where the bot is hosted (e.g., `https://your-bot.cloudfunctions.net`).
- `GITHUB_APP_ID`: Your GitHub App ID.
- `GITHUB_APP_PRIVATE_KEY_B64`: Your GitHub App's private key, encoded in Base64.
- `GITHUB_APP_SLUG`: The URL-friendly name of your GitHub App.

### Security Variables (Recommended for Production)
- `SECRET_KEY`: Used by Flask to sign session cookies. 
    - **Usage**: Encrypting the `discord_user_id` during the `/link` flow.
    - **Manual Check**: If you change this key while a user is mid-authentication, their session will be invalidated, and they will see "Authentication failed: No Discord user session".
    - **Generation**: `python3 -c "import secrets; print(secrets.token_hex(32))"`

### Feature-Specific Variables (Optional/Disabled)
- `GITHUB_WEBHOOK_SECRET`: Required ONLY for PR automation. Used to verify that webhooks are actually coming from GitHub.
- `GITHUB_TOKEN`: Original personal access token (largely replaced by GitHub App identity).
- `REPO_OWNER` / `REPO_NAME`: Used for triggering the initial sync pipeline. Defaults to `ruxailab/disgitbot`.

---

## Re-enabling PR Automation

PR automation is currently commented out to simplify the SaaS experience. To re-enable it:

### 1. Uncomment Command Registration
In [discord_bot/src/bot/commands/admin_commands.py](file:///home/justin/opensource/disgitbot/discord_bot/src/bot/commands/admin_commands.py):
```python
# In register_commands():
self.bot.tree.add_command(self._add_reviewer_command())
self.bot.tree.add_command(self._remove_reviewer_command())
```

In [discord_bot/src/bot/commands/notification_commands.py](file:///home/justin/opensource/disgitbot/discord_bot/src/bot/commands/notification_commands.py):
```python
# In register_commands():
# self.bot.tree.add_command(self._webhook_status_command())
```

### 2. Configure GitHub App Webhooks
1. Go to your GitHub App settings.
2. Enable **Webhooks**.
3. **Webhook URL**: `{OAUTH_BASE_URL}/github-webhook`
4. **Webhook Secret**: Set a random string and update `GITHUB_WEBHOOK_SECRET` in your `.env`.
5. **Permissions & Events**:
    - Push: `read & write` (checks)
    - Pull Requests: `read & write`
    - Repository metadata: `read-only`
    - Subscribe to: `Pull request`, `Push`, `Workflow run`.

### 3. Async Architecture Note
All Firestore calls in this codebase must be offloaded to a thread pool when called from an async context (like command handlers). Always use the following pattern:

```python
result = await asyncio.to_thread(get_document, 'collection', 'doc_id', discord_server_id)
```

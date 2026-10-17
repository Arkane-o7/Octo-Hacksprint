# Connect Octo to a demo Google account

This requires manual Google consent. The local helper creates one **Octo Demo** Drive folder
and one **Octo Demo** secondary calendar after you grant access. Use your chosen
demo account. It does not use your primary calendar or change sharing.

## 1. Create the client in Google Cloud

1. Open [Google Cloud Console](https://console.cloud.google.com/) and create/select
   a project such as **Octo Demo**.
2. Open **APIs & Services → Library**. Enable **Google Drive API** and
   **Google Calendar API** in that project.
3. Open **Google Auth Platform** (or OAuth consent screen). Set the app name to
   **Octo Demo**, your support email, and developer contact email.
4. Under **Audience**, choose **External** for a normal Gmail test account,
   keep publishing status **Testing**, and add the Google email you will sign in
   with under **Test users**. An organization can impose separate restrictions.
5. Under **Data Access**, add these scopes:
   - `https://www.googleapis.com/auth/drive.file`
   - `https://www.googleapis.com/auth/calendar.app.created`
6. Under **Clients → Create client**, choose **Desktop app**, name it **Octo Mac**,
   and download its JSON. A Web application client is not interchangeable.
7. Save it locally as `data/google-client.json` inside your Octo checkout.
   Do not paste the JSON, client secret, or refresh token into chat.

## 2. Run the local setup command

```sh
cd /path/to/Octo
uv run python -m octo.google_setup --client-secret data/google-client.json
```

Your normal browser opens Google's consent page. Choose the intended demo
account and allow both requested permissions. Return to the terminal afterward.
The command waits up to ten minutes. It uses a temporary `127.0.0.1` loopback
callback, OAuth state validation and PKCE; there is no public callback server
or authorization code to paste manually.

On success the helper saves:

- `data/google-oauth.json`: local authorized-user credentials, mode `0600`.
- `data/google-resources.json`: the two confirmed demo resource IDs.
- `.env`: Drive/Calendar credential paths, folder ID, calendar ID.

Rerunning reuses and checks the saved resources instead of creating duplicates.
No access/refresh tokens are printed. These files are ignored by Git.

## 3. Restart and test

Tell Codex **“Google setup finished”** so the existing single worker can be
restarted safely. Do not start a second copy while the current worker owns 8018.
If running the app yourself, stop that worker and run:

```sh
uv run python -m uvicorn octo.app:app --host 0.0.0.0 --port 8018
```

After configuration, existing clear, future-dated, class-wide records are queued
for Calendar sync; new records are queued as they are saved. No private/student
records go into the shared calendar. Undated, past or unclear records are skipped.
Entries are **all-day** because Octo does not yet store reliable start/end times.
Calendar sends no invitations and uses no default reminders; Octo's existing
WhatsApp reminder queue owns reminders. The app must stay running.

In the demo group, send a fresh future-dated notice such as:

> Class 5B: Please bring crayons and a drawing book on 20 October 2026.

Expect the saved notice, then a real Calendar link after Google confirms the
write. Check the **Octo Demo** calendar in Google Calendar. An app health response
or mocked test is not proof of live Calendar access.

For Drive, resend a small PDF with one clear subject/chapter, e.g. caption
**Science — Chapter 6 notes for Class 5B**. Expect a real Drive link after upload.
Existing locally retained PDFs are not uploaded automatically. Open the link in
the intended viewer's Google account to verify access. If needed, manually share
the demo folder/calendar with that account; Octo never makes them public.

## Recovery

- `access_denied` / test-user error: check the exact signed-in account is listed
  under Audience → Test users and both APIs are enabled in this project.
- `redirect_uri_mismatch`: download a **Desktop app** client, not a Web client.
- Expired/revoked consent: run the command again with `--reauthorize`. Google
  documents a seven-day refresh-token expiry for External apps in Testing with
  these scopes. Re-consent before the hackathon if necessary.
- Unconfirmed resource creation: the helper stops instead of creating a second
  folder/calendar. Inspect Google, then update that entry in
  `data/google-resources.json` to `{"status":"created","id":"actual ID"}` if
  the resource exists. Remove the entry only after confirming it was not created.
  Rerun; the helper verifies access. `drive.file` cannot access an arbitrary
  pre-existing folder merely because its ID is pasted in.
- A Calendar job retries at most three times. After fixing OAuth, run
  `uv run python -m octo.google_setup --retry-calendar` to queue failed jobs again;
  do not resend the notice just to force a new event. Deterministic IDs reconcile
  uncertain API writes. Existing records stay saved even if Google fails.

Official references:
[desktop OAuth](https://developers.google.com/identity/protocols/oauth2/native-app),
[Drive scopes](https://developers.google.com/workspace/drive/api/guides/api-specific-auth),
[Calendar scopes](https://developers.google.com/workspace/calendar/api/auth),
[secondary-calendar creation](https://developers.google.com/workspace/calendar/api/v3/reference/calendars/insert),
[testing token expiry](https://developers.google.com/identity/protocols/oauth2#expiration).

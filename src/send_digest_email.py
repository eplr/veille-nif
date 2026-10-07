"""Envoi de la veille par email : Microsoft Graph ou SMTP, destinataires en copie cachée.

Aucun identifiant ni adresse n'est dans le dépôt (public) : tout vient de variables d'environnement,
à définir comme secrets GitHub.

Les destinataires de la communauté (DIGEST_TO) sont toujours mis en copie cachée : chaque membre ne voit
que l'expéditeur. Le champ « À » affiche l'expéditeur lui-même (ou DIGEST_VISIBLE_TO s'il est défini).

Backend Microsoft Graph (recommandé pour une boîte Microsoft 365) :
    EMAIL_BACKEND=graph  (ou omis si GRAPH_CLIENT_ID est défini)
    GRAPH_TENANT_ID, GRAPH_CLIENT_ID, GRAPH_CLIENT_SECRET
    DIGEST_FROM    boîte au nom de laquelle envoyer (permission applicative Mail.Send)
    DIGEST_TO      destinataires, séparés par des virgules (copie cachée)

Backend SMTP classique :
    EMAIL_BACKEND=smtp
    SMTP_HOST, SMTP_PORT (587 STARTTLS ou 465 SSL/TLS), SMTP_USER, SMTP_PASSWORD
    DIGEST_TO, DIGEST_FROM (optionnel, par défaut SMTP_USER)

Test (envoie un message minimal à DIGEST_TEST_TO, ou à DIGEST_FROM à défaut) :
    python src/send_digest_email.py --test
"""
import argparse
import os
import re
import smtplib
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests

GRAPH_TOKEN_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
GRAPH_SENDMAIL_URL = "https://graph.microsoft.com/v1.0/users/{user}/sendMail"


def _markdown_to_html(md: str) -> str:
    """Conversion minimale, suffisante pour un message de test (pas un vrai parseur Markdown)."""
    lines = []
    for line in md.split("\n"):
        line = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', line)
        if line.startswith("### "):
            lines.append(f"<h3>{line[4:]}</h3>")
        elif line.startswith("## "):
            lines.append(f"<h2>{line[3:]}</h2>")
        elif line.startswith("# "):
            lines.append(f"<h1>{line[2:]}</h1>")
        elif line.startswith("- "):
            lines.append(f"<li>{line[2:]}</li>")
        elif line.strip() == "---":
            lines.append("<hr>")
        elif line.strip() == "":
            lines.append("<br>")
        else:
            lines.append(f"<p>{line}</p>")
    return '<html><body style="font-family: sans-serif;">' + "\n".join(lines) + "</body></html>"


def split_addresses(value: str) -> list[str]:
    return [a.strip() for a in (value or "").split(",") if a.strip()]


def _choose_backend() -> str:
    backend = os.environ.get("EMAIL_BACKEND")
    if backend:
        return backend.lower()
    return "graph" if os.environ.get("GRAPH_CLIENT_ID") else "smtp"


def _send_via_graph(subject: str, body_html: str, from_addr: str, visible_to: list[str], bcc: list[str]):
    tenant = os.environ.get("GRAPH_TENANT_ID")
    client_id = os.environ.get("GRAPH_CLIENT_ID")
    client_secret = os.environ.get("GRAPH_CLIENT_SECRET")
    missing = [k for k, v in {
        "GRAPH_TENANT_ID": tenant, "GRAPH_CLIENT_ID": client_id, "GRAPH_CLIENT_SECRET": client_secret,
    }.items() if not v]
    if missing:
        raise SystemExit(f"Variables Graph manquantes : {', '.join(missing)}")

    token_resp = requests.post(
        GRAPH_TOKEN_URL.format(tenant=tenant),
        data={
            "grant_type": "client_credentials", "client_id": client_id, "client_secret": client_secret,
            "scope": "https://graph.microsoft.com/.default",
        },
        timeout=15,
    )
    if token_resp.status_code != 200:
        # Le corps de la réponse n'est pas affiché : il peut contenir des identifiants.
        raise RuntimeError(f"Authentification Graph échouée : HTTP {token_resp.status_code}")
    token = token_resp.json()["access_token"]

    message = {
        "subject": subject,
        "body": {"contentType": "HTML", "content": body_html},
        "toRecipients": [{"emailAddress": {"address": a}} for a in visible_to],
        "bccRecipients": [{"emailAddress": {"address": a}} for a in bcc],
    }
    resp = requests.post(
        GRAPH_SENDMAIL_URL.format(user=from_addr),
        json={"message": message, "saveToSentItems": "true"},
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    if resp.status_code not in (200, 202):
        raise RuntimeError(f"Graph sendMail a échoué : HTTP {resp.status_code}")


def _send_via_smtp(subject: str, body_markdown: str, body_html: str, from_addr: str,
                   visible_to: list[str], bcc: list[str]):
    host = os.environ.get("SMTP_HOST")
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASSWORD")
    missing = [k for k, v in {"SMTP_HOST": host, "SMTP_USER": user, "SMTP_PASSWORD": password}.items() if not v]
    if missing:
        raise SystemExit(f"Variables SMTP manquantes : {', '.join(missing)}")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = ", ".join(visible_to)  # pas d'en-tête Bcc : les destinataires cachés ne figurent que dans l'enveloppe
    msg.attach(MIMEText(body_markdown, "plain", "utf-8"))
    msg.attach(MIMEText(body_html, "html", "utf-8"))
    envelope = visible_to + bcc

    if port == 465:
        with smtplib.SMTP_SSL(host, port, timeout=30) as server:
            server.login(user, password)
            server.sendmail(from_addr, envelope, msg.as_string())
    else:
        with smtplib.SMTP(host, port, timeout=30) as server:
            server.starttls()
            server.login(user, password)
            server.sendmail(from_addr, envelope, msg.as_string())


def send_email(subject: str, body_markdown: str, body_html: str | None = None, to_override: str | None = None):
    """Envoie le message. `to_override` remplace DIGEST_TO (utilisé par --test)."""
    recipients = split_addresses(to_override or os.environ.get("DIGEST_TO", ""))
    from_addr = os.environ.get("DIGEST_FROM") or os.environ.get("SMTP_USER")
    if not recipients:
        raise SystemExit("Variable manquante : DIGEST_TO (liste de destinataires séparés par des virgules)")
    if not from_addr:
        raise SystemExit("Variable manquante : DIGEST_FROM (ou SMTP_USER en backend smtp)")
    visible_to = split_addresses(os.environ.get("DIGEST_VISIBLE_TO", "")) or [from_addr]
    html = body_html or _markdown_to_html(body_markdown)

    backend = _choose_backend()
    if backend == "graph":
        _send_via_graph(subject, html, from_addr, visible_to, recipients)
    elif backend == "smtp":
        _send_via_smtp(subject, body_markdown, html, from_addr, visible_to, recipients)
    else:
        raise SystemExit(f"EMAIL_BACKEND inconnu : {backend!r} (attendu : graph ou smtp)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--test", action="store_true", help="envoyer un message de test minimal")
    args = parser.parse_args()
    if not args.test:
        print(__doc__)
        sys.exit(1)
    target = os.environ.get("DIGEST_TEST_TO") or os.environ.get("DIGEST_FROM") or os.environ.get("SMTP_USER")
    send_email(
        subject="Test – veille Nature in Finance",
        body_markdown="# Test\nCeci est un message de test envoyé par `send_digest_email.py --test`.",
        to_override=target,
    )
    print(f"[send-digest-email] message de test envoyé via le backend {_choose_backend()!r}")

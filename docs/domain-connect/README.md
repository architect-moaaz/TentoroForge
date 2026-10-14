# Domain Connect templates

The two templates Forge applies when an owner approves an address's DNS records at their own DNS provider
(`backend/services/deploy/domain_connect.py`). The file name follows the template repository's convention,
`<providerId>.<serviceId>.json`.

To make the **Connect with <provider>** button appear:

1. Make a key pair (`openssl genrsa -out dc-key.pem 2048`). Keep the private key with the platform's other
   secrets as `FORGE_DOMAIN_CONNECT_KEY`; never commit it.
2. Publish its public half as TXT records at `_dck1.tentoro.ai`:
   `python -m services.deploy.domain_connect key-records dc-key.pem` prints them (public key only).
3. Set `FORGE_DOMAIN_CONNECT_DOMAIN=tentoro.ai` and `FORGE_APP_BASE_URL` (where owners come back to).
4. Submit these files to https://github.com/Domain-Connect/Templates and ask each DNS provider to onboard them.
   A provider shows the button only once it holds the template.

## Where things stand

- Signing key made 2026-10-15; the private half is kept outside any repository
  (`~/.config/forge/domain-connect/tentoro-dc-signing-key.pem` on the machine that made it).
- Public key: two TXT records at `_dck1.tentoro.ai` (tentoro.ai's DNS is at GoDaddy).
- Templates submitted: https://github.com/Domain-Connect/Templates/pull/2333 (both pass `dc-template-linter`
  full, logo and fast-track checks; Online Editor tests linked in the PR).

## Onboarding, after the templates merge

Onboarding is not automatic: each DNS provider is asked by email, and some want terms signed or review the
template again. Contacts from https://www.domainconnect.org/dns-providers/:

| DNS provider | Contact |
|---|---|
| GoDaddy | domainconnect@godaddy.com |
| IONOS | domain_connect_admin@domain.ionos.com |
| Cloudflare | domain-connect@cloudflare.com (see developers.cloudflare.com/dns/reference/domain-connect/) |
| NameSilo | domainconnect@namesilo.com |
| Plesk | domainconnect@plesk.com |
| WordPress.com | registrar@automattic.com |
| Domain Chief | https://aka.chief.app/domainconnect |
| Glauca Digital | hello@glauca.digital |

Route 53, Namecheap and Squarespace do not take part; owners there use a connected DNS account or add the
records by hand.

`test_the_owner_approves_at_their_provider.py` fails if these files drift from what the code signs for.

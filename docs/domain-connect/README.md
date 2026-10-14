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

`test_the_owner_approves_at_their_provider.py` fails if these files drift from what the code signs for.

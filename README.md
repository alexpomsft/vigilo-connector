# vigilo-connector

Personlig MCP-connector mot [Vigilo](https://vigilo.no) sitt (uoffisielle)
foreldre-API, slik at en agent kan lese beskjeder, timeplan, fravær, samtykker,
nyheter m.m. og aksjonere på dem. Auth-flyten er inspirert av kartleggingen i
[brujoand/vigilo2smtp](https://github.com/brujoand/vigilo2smtp).

**Kun til personlig bruk** med egen foreldretilgang. API-et er reverse-engineert
og kan endres av Vigilo uten varsel — respektér Vigilos vilkår, og ikke hent mer
data enn du selv har tilgang til. Tokens og data holdes lokalt
(`~/.config/vigilo-connector/`, chmod 600) og legges aldri inn i repoet.

## Status for denne forken

Denne forken fjerner de generiske MCP-verktøyene `api_get` og `web_api_get`.
Autentiserte forespørsler er begrenset til navngitte, tillatte API-ruter på
faste HTTPS-domener. Absolutte URL-er, ukjente ruter, sti-traversering og
redirects kan ikke brukes til å sende tilgangstokenet til et annet mål.

Dette er sikkerhetsherding av den eksisterende klienten, **ikke en verifisert
Oslo-integrasjon eller en lokal eksportløsning**. Ikke koble MCP-serveren til
en ekstern briefing: den returnerer rå kontodata og er ikke avgrenset til ett
barn. Vedleggsverktøyene laster ned innhold og skal ikke brukes i den første
innsamlingsfasen.

## To API-er

Connectoren har operasjoner for to endepunkter:

- **App-gateway** (`api-gw-parent-app.prod.vigilo-oas.no`) — beskjeder/tråder.
- **Web-foreldreportal** (`web-parent.prod.vigilo-oas.no`) — timeplan, fravær,
  samtykker, nyheter, vurdering. Det Vigilo-appen ikke eksponerer.

Den eksisterende innloggingen krever en konfidensiell OAuth2-klient med
client_id/secret, uten PKCE. Denne forken skaffer ikke slike credentials.
Aksept av samme token hos begge API-er, Oslo/AKS-dekning og levetid for
refresh-token er ikke verifisert her.

## Oppsett

### Lokal installasjon og offline-tester

```bash
python3 -m venv .venv && .venv/bin/pip install -e .
.venv/bin/python -m unittest discover -s tests -v
```

Testene bruker fiktive tokens og HTTPX MockTransport, ikke ekte Vigilo-data.
Det finnes ikke en godkjent innloggingsmetode for briefing-integrasjonen i
denne forken ennå. Ikke hent klienthemmeligheter fra APK-er eller del tokens,
cookies, callback-URL-er eller nettverksopptak med en agent eller ekstern server.

### MCP-server (ikke en minimert eksport)

```bash
claude mcp add vigilo -- /path/to/vigilo-connector/.venv/bin/vigilo-mcp
```

(Bytt `/path/to/vigilo-connector` med din egen sti til repoet.)

#### Alternativ: JSON-konfig (import / manuell registrering)

Klienter som importerer MCP-servere fra JSON kan bruke denne blokken:

```json
{
  "mcpServers": {
    "vigilo": {
      "command": "/path/to/vigilo-connector/.venv/bin/vigilo-mcp"
    }
  }
}
```

Skal du legge den til manuelt i en klient (MCP → sett opp manuelt), bruk
stdio-transport med samme kommando:

```json
{
  "transport": "stdio",
  "command": "/path/to/vigilo-connector/.venv/bin/vigilo-mcp"
}
```

## Verktøy

| Verktøy | Gjør |
|---|---|
| `web_list_children` | Barna dine med `childId` **og** `organizationalUnitId` (skole/klasse) |
| `list_children` | Barna via app-gatewayen (kun `childId`) |
| `list_message_threads` / `get_message_thread` | Beskjedtråder og meldinger (app-gateway) |
| `read_message_attachments` | Last ned og les vedlegg i en meldingstråd (PDF/docx→tekst) |
| `read_post_attachments` | Last ned og les vedlegg i et oppslag/«Siste nytt» (PDF/docx→tekst) — her ligger ofte ukeplanen |
| `news_feed` | «Siste nytt» / oppslag for et barn |
| `absences` | Fravær for et barn |
| `consent_forms` | Samtykkeskjemaer (krever `organizationalUnitId`) |
| `timetable` | Timeplan/ukesplan for en ISO-uke |
| `scheduling_events` | Prøver/aktiviteter i timeplanen for en uke |

`childId` og `organizationalUnitId` får du fra `web_list_children`; begge er
UUID-er. `week` er ISO-format `YYYY-WW` (default inneværende uke).

## Kartlagte web-endepunkter

Ruter fra upstream-kartleggingen, ikke live-verifisert for Oslo i denne forken.
Base `https://web-parent.prod.vigilo-oas.no`, alle GET, Bearer-auth.
GET garanterer ikke at en melding forblir ulest.

- `/api/children/my` — barn (childId + `organizationalUnits`)
- `/api/news-feed?childIds=&fromDate=&toDate=`
- `/api/message-threads?childIds=&fromDate=&toDate=`
- `/api/absences?childIds=`
- `/api/consent-forms?childId=&organizationalUnitId=`
- `/api/students/{childId}/lessons?organizationalUnitId=&week=YYYY-WW`
- `/api/scheduling-events/{childId}/student?organizationalUnitId=&week=YYYY-WW`
- `/api/school-years?organizationalUnitId=`

## Videre arbeid

Verifiser først offisiell web-innlogging i en dedikert lokal nettleserprofil,
med manuell ID-porten og pause under sensitiv inntasting. Observer ekte ruter,
lesestatus, originaldatoer, skole/AKS-dekning og senere gjenbruk av sesjonen
før en fast-rute-adapter vurderes. Ikke anta at mobilklientens refresh-mekanisme
gjelder nettleseren.

En eventuell collector skal eksportere minimert innhold for bare det valgte
barnet, med originale tidsstempler og eksplisitte dekningsbegrensninger.
Nettlesercredentials blir lokale. Start uten vedleggsinnhold, og uten svar,
samtykkeendringer, fraværsinnsending eller kalenderskriving. Oppsettet over
starter eller planlegger ingen slik collector.

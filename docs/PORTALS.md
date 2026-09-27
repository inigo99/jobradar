# Job portals to add

JobRadar ships with a few general sources (EURES and the remote-work
boards). Everything more local — a region's employment
service, a country's public-sector jobs, a national board — you add yourself
under **Settings → Job portals you use**, where each one can be switched off,
edited or deleted without losing it.

Copy the lines you want and paste them into the box under the list: several
at once, one per line, optionally with a name before the address. Where the
address contains `{query}`, JobRadar searches it once for each job title you
look for; searches work best with the title in the portal's language.

Every portal below was checked on **27 September 2026**: the live page's
structure against what JobRadar's reader understands, and the site's
`robots.txt` against the address. Sites
change: if one stops yielding offers, the run history says so — please
[open an issue](https://github.com/inigo99/jobradar/issues/new/choose) or
send a pull request updating this list.

How each is read:

- **search** — a results page for your titles, read by the links whose text
  matches them;
- **feed** — an RSS feed of the newest offers, filtered by your titles;
- **page** — a page of the newest offers, read by matching links.

## Spain

### Every region at once

The Sistema Nacional de Empleo gathers the offers every regional public
employment service puts out for applicants (SAE, Lanbide, SEPE Madrid, SOC,
Labora…), in every sector. One search covers them all (tested live on 27
September 2026: 35 offers for "enfermera", each read with its full text):

```text
Sistema Nacional de Empleo (toda España) https://www.sistemanacionalempleo.es/OfertaDifusionWEB/busquedaOfertas.do?modo=continuar&palabraBusqueda={query}&botonNavegacion=Enviar
```

Its search looks for the whole phrase, so short job titles find far more:
"recursos humanos" finds 13 offers where "técnico de recursos humanos" finds
one, and "nóminas" finds the payroll jobs. Put the short forms among your
job titles (Settings → What to search) — JobRadar still matches the long ones
against each offer's title, synonyms included.

### One region

The Sistema Nacional de Empleo's search for a single autonomous community
only works through its form (it keeps the chosen region in the visitor's
session), so it cannot be added as an address. Use the search above; each
offer's text, which JobRadar reads and scores, gives its town and province.

Some regional services also publish offers only on their own site. The
Servicio Navarro de Empleo's list is read as a **page** (its newest ten
offers):

```text
Servicio Navarro de Empleo https://administracionelectronica.navarra.es/EmpleoIntermediacion/listadodeofertas
```

### Public-sector jobs (oposiciones)

The Boletín Oficial del Estado publishes every state competition for public
posts — teachers, doctors and nurses in public health, university staff,
civil servants. The feeds cover the last two months; titles are the official
resolutions, so match on words that appear in them ("profesor", "enfermero",
"técnico").

```text
BOE Oposiciones https://www.boe.es/rss/canal_per.php?l=p&c=140
BOE Concursos de personal https://www.boe.es/rss/canal_per.php?l=p&c=141
```

## Portugal

Net-Empregos, the largest general board, publishes its newest offers as a
feed (its search pages are closed to automated readers by its `robots.txt`):

```text
Net-Empregos (últimas ofertas) https://www.net-empregos.com/rss.asp
```

## France

France Travail's search pages (`?motsCles=…`) are closed to automated
readers by its `robots.txt`, but its pages per occupation are open. Search
your occupation on [candidat.francetravail.fr](https://candidat.francetravail.fr),
open the occupation page (an address shaped like
`/offres/emploi/<occupation>/<code>`) and paste that address — for nurses:

```text
France Travail — infirmier https://candidat.francetravail.fr/offres/emploi/infirmier/s36m2
```

## Italy

```text
Cercolavoro (ultime offerte) https://www.cercolavoro.com/rss/offerte+lavoro+rss.jsp
```

## Germany

The Bundesagentur für Arbeit, Germany's public employment service, has every
sector. JobRadar reads it through the agency's own search API, which gives
cleaner offers (title, employer, date and full text) than its web pages, so
it is built in rather than pasted: add `DE` to your countries and it is on
(or switch on **Bundesagentur für Arbeit** under **Settings → Sources**).

## Everywhere else in Europe

EURES, built in, already carries the offers of every EU/EEA public
employment service: Italy's centri per l'impiego, Ireland's Intreo, the
Netherlands' UWV, Portugal's IEFP… Add a national board here only when most
of your field's offers are posted there and nowhere else.

## Adding a portal to this list

A portal works when its offers are in the HTML the server sends (not built
afterwards by JavaScript) or in a feed, and its `robots.txt` lets automated
readers in. To check one, add it in Settings, run a search and look at the
run history: offers found, or a note saying why not. Then send a pull
request adding it here, under its country, with how it is read and the date
you checked it.

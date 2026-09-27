# Job portals to add

JobRadar ships with a few general sources (EURES, the German employment
agency, remote-work boards). Everything more local — a region's employment
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
Labora…), in every sector. One search covers them all:

```text
Sistema Nacional de Empleo (toda España) https://www.sistemanacionalempleo.es/OfertaDifusionWEB/busquedaOfertas.do?modo=continuar&palabraBusqueda={query}&botonNavegacion=Enviar
```

### One region

The same search limited to one autonomous community — add yours instead of
the one above if you only look near home:

```text
SNE Andalucía https://www.sistemanacionalempleo.es/OfertaDifusionWEB/busquedaOfertas.do?modo=continuar&CA=01&palabraBusqueda={query}&botonNavegacion=Enviar
SNE Aragón https://www.sistemanacionalempleo.es/OfertaDifusionWEB/busquedaOfertas.do?modo=continuar&CA=02&palabraBusqueda={query}&botonNavegacion=Enviar
SNE Asturias https://www.sistemanacionalempleo.es/OfertaDifusionWEB/busquedaOfertas.do?modo=continuar&CA=03&palabraBusqueda={query}&botonNavegacion=Enviar
SNE Illes Balears https://www.sistemanacionalempleo.es/OfertaDifusionWEB/busquedaOfertas.do?modo=continuar&CA=04&palabraBusqueda={query}&botonNavegacion=Enviar
SNE Canarias https://www.sistemanacionalempleo.es/OfertaDifusionWEB/busquedaOfertas.do?modo=continuar&CA=05&palabraBusqueda={query}&botonNavegacion=Enviar
SNE Cantabria https://www.sistemanacionalempleo.es/OfertaDifusionWEB/busquedaOfertas.do?modo=continuar&CA=06&palabraBusqueda={query}&botonNavegacion=Enviar
SNE Castilla-La Mancha https://www.sistemanacionalempleo.es/OfertaDifusionWEB/busquedaOfertas.do?modo=continuar&CA=07&palabraBusqueda={query}&botonNavegacion=Enviar
SNE Castilla y León https://www.sistemanacionalempleo.es/OfertaDifusionWEB/busquedaOfertas.do?modo=continuar&CA=08&palabraBusqueda={query}&botonNavegacion=Enviar
SNE Cataluña https://www.sistemanacionalempleo.es/OfertaDifusionWEB/busquedaOfertas.do?modo=continuar&CA=09&palabraBusqueda={query}&botonNavegacion=Enviar
SNE Comunitat Valenciana https://www.sistemanacionalempleo.es/OfertaDifusionWEB/busquedaOfertas.do?modo=continuar&CA=10&palabraBusqueda={query}&botonNavegacion=Enviar
SNE Extremadura https://www.sistemanacionalempleo.es/OfertaDifusionWEB/busquedaOfertas.do?modo=continuar&CA=11&palabraBusqueda={query}&botonNavegacion=Enviar
SNE Galicia https://www.sistemanacionalempleo.es/OfertaDifusionWEB/busquedaOfertas.do?modo=continuar&CA=12&palabraBusqueda={query}&botonNavegacion=Enviar
SNE Comunidad de Madrid https://www.sistemanacionalempleo.es/OfertaDifusionWEB/busquedaOfertas.do?modo=continuar&CA=13&palabraBusqueda={query}&botonNavegacion=Enviar
SNE Región de Murcia https://www.sistemanacionalempleo.es/OfertaDifusionWEB/busquedaOfertas.do?modo=continuar&CA=14&palabraBusqueda={query}&botonNavegacion=Enviar
SNE Navarra https://www.sistemanacionalempleo.es/OfertaDifusionWEB/busquedaOfertas.do?modo=continuar&CA=15&palabraBusqueda={query}&botonNavegacion=Enviar
SNE País Vasco https://www.sistemanacionalempleo.es/OfertaDifusionWEB/busquedaOfertas.do?modo=continuar&CA=16&palabraBusqueda={query}&botonNavegacion=Enviar
SNE La Rioja https://www.sistemanacionalempleo.es/OfertaDifusionWEB/busquedaOfertas.do?modo=continuar&CA=17&palabraBusqueda={query}&botonNavegacion=Enviar
```

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
Cercolavoro (ultime offerte) http://www.cercolavoro.com/rss/offerte+lavoro+rss.jsp
```

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

# Starter configurations

*[Leer en español](STARTER_CONFIGS.es.md)*

A first configuration for nineteen professions, to start searching the day you
install JobRadar and adjust from there. They come from testing JobRadar with
graduate profiles in Navarra and Madrid (see [benchmarks/](../benchmarks/README.md)),
so they lean towards someone starting out in Spain; the reasoning carries over
to other places.

Everything below is set in the dashboard — **Settings → What you're looking
for**, **Filters** and **Where to search** — or in a `settings.yaml` loaded with
`jobradar init --config settings.yaml` (full reference in
[CONFIGURATION.md](CONFIGURATION.md)).

## What makes the difference

Most searches that find nothing are not missing offers: they are asking for
them in words the ads do not use, or in places that do not publish them.

1. **Titles are words ads put in their titles.** A board's results are kept
   only when their title matches one of yours, so write what an employer
   writes: "abogado", "jurídico", "enfermera", "electricista" — not "Consultor
   Legal Tech" or "Director de Residencia Universitaria". Gender and plural do
   not matter ("enfermera" finds "Enfermero/a"). Four to eight titles is plenty.
2. **Leave extra keywords empty** at first. Each one is one more search on every
   board, and general words ("APPCC", "Hospitality Management") bring noise,
   not offers.
3. **Add the area pages of your field as portals.** Public services and
   EURES publish few offers in some fields (law, marketing, design,
   engineering) and some regions (Navarra). A board's page for one field in
   one province lists exactly what you want. For Infoempleo the address is
   `https://www.infoempleo.com/trabajo/area-de-empresa_<area>/en_<province>/`,
   with the area from each profession below and the province as Infoempleo
   writes it (`navarra`, `madrid`, `barcelona`…). Add the
   Sistema Nacional de Empleo search as well — it covers every region:
   `https://www.sistemanacionalempleo.es/OfertaDifusionWEB/busquedaOfertas.do?modo=continuar&palabraBusqueda={query}&botonNavegacion=Enviar`.
   More in [PORTALS.md](PORTALS.md).
4. **Your area, and whether it is a limit.** Put your city in *Areas*. Tick
   *Only in these areas* if you would not move: offers elsewhere in the country
   go to *Filtered out* instead of the board. Add *Remote* to the work modes
   where the profession allows it.
5. **Years: let your CV decide.** Keep *Take the ceiling from my CV's own dates*
   on, with a margin of 1 year. Ads asking for a little more than you have are
   set apart as *just short* in *Filtered out* — for a graduate they are often
   worth a direct email.
6. **Salary: leave it empty, or use the floor below.** Only a published salary
   rejects an offer; an estimate never does. The floors given are the bottom of
   JobRadar's own junior band for the family, a Spain-level reference — raise
   them if you know your market.
7. **Ads up to 30 days old** when you start (public services publish slowly),
   then 7–14 once you search every day.
8. **LinkedIn, InfoJobs and Indeed** carry most private-sector offers in law,
   marketing, design and engineering. They are off by default: switching them
   on is your decision under each site's terms (see [SOURCES.md](SOURCES.md)).
9. **Search once a day at most.** Public boards limit automated readers; when
   one refuses, the run says so and its offers are missing that day.

## A complete example

Nursing, in Pamplona, not moving:

```yaml
search:
  titles: [enfermera, enfermero, enfermería]
  keywords: []
  languages: [es]

filters:
  work_modes: [onsite, hybrid]
  local_areas: [Pamplona]
  local_only: true
  home_country: ES
  min_salary:                     # empty: no salary filter
  use_profile_years: true
  years_margin: 1.0
  max_age_days: 30

sources:
  enabled: [eures, portals]       # add linkedin, infojobs, indeed if you choose to
  portals:
    - {name: Sistema Nacional de Empleo, url: "https://www.sistemanacionalempleo.es/OfertaDifusionWEB/busquedaOfertas.do?modo=continuar&palabraBusqueda={query}&botonNavegacion=Enviar"}
    - {name: Infoempleo — sanidad en Navarra, url: "https://www.infoempleo.com/trabajo/area-de-empresa_sanidad-salud-y-servicios-sociales/en_navarra/"}

families:
  healthcare: {priority: 1.3}     # your field first on the board
```

For another profession, change the titles, the Infoempleo area, the work modes
and the family as in its entry below.

## By profession

Each entry gives the **titles** to search, the **work modes** worth accepting,
the **Infoempleo area** (for the address above), the **job family** to put
first, and a **salary floor** if you want one.

### Health

**Nursing** — titles: `enfermera, enfermero, enfermería` · on-site ·
area `sanidad-salud-y-servicios-sociales` · family `healthcare` · floor 20,000 €.
Hospitals and care homes publish through the public services too; EURES and the
Sistema Nacional de Empleo find them well in Madrid, much less in Navarra.

**Physiotherapy** — titles: `fisioterapeuta, fisioterapia` · on-site ·
area `sanidad-salud-y-servicios-sociales` · family `healthcare` · floor 20,000 €.

**Psychology** — titles: `psicólogo, psicóloga, psicólogo sanitario` (add
`técnico de selección` if you would take HR) · on-site, hybrid ·
area `sanidad-salud-y-servicios-sociales` (and `recursos-humanos`) ·
family `healthcare` · floor 20,000 €.

**Dentistry** — titles: `odontólogo, dentista, odontología` · on-site ·
area `sanidad-salud-y-servicios-sociales` · family `healthcare` · floor 20,000 €.
In our tests the public boards had no dentist offers in Navarra or Madrid:
look to InfoJobs, Indeed and the clinics' own pages.

**Dental hygiene** — titles: `higienista dental, higienista bucodental,
auxiliar de clínica dental` · on-site · area `sanidad-salud-y-servicios-sociales` ·
family `healthcare` · floor 20,000 €.

### Education and social

**Primary teaching** — titles: `maestro, maestra, profesor de primaria,
profesor de inglés` · on-site · area `educacion-formacion` · family `education` ·
floor 18,000 €. Public posts go through *oposiciones*: add the BOE feeds from
[PORTALS.md](PORTALS.md).

**Social work** — titles: `trabajador social, trabajadora social, educador
social, integrador social` · on-site · area `sanidad-salud-y-servicios-sociales` ·
family `care_social` · floor 17,000 €.

### Law and business

**Law** — titles: `abogado, jurídico, jurista, derecho, protección de datos,
compliance, asistente jurídico` · on-site, hybrid, remote · area `legal` ·
family `legal` · floor 20,000 €. Tested in Madrid: with these titles and the
legal area page, a search that found nothing found four offers, the best a 98 %
match. Add the Colegio de Abogados' notice board of your city if it has one
([PORTALS.md](PORTALS.md) lists Pamplona's).

**Business administration (ADE)** — titles: `analista financiero, contable,
controller, administración, auxiliar contable` · on-site, hybrid ·
areas `banca-finanzas-y-seguros`, `administracion-de-empresas` ·
family `finance_accounting` · floor 20,000 €.

**Administration and finance (vocational)** — titles: `administrativo,
auxiliar administrativo, administrativo contable, contable` · on-site, hybrid ·
area `administrativos-y-secretariado` · family `administration_office` ·
floor 16,000 €.

### Communication and design

**Marketing** — titles: `marketing, marketing digital, community manager,
SEO, redes sociales` · on-site, hybrid, remote · area `marketing-publicidad-y-rrpp`
(and `digital` where it exists, as in Madrid) · family `marketing_communication` ·
floor 18,000 €.

**Journalism** — titles: `periodista, redactor, redactora, comunicación,
community manager` · on-site, hybrid, remote · areas
`medios-editorial-y-artes-graficas` (Madrid), `marketing-publicidad-y-rrpp` ·
family `marketing_communication` · floor 18,000 €.

**Graphic design** — titles: `diseñador gráfico, diseñadora gráfica,
diseño gráfico, maquetador, UX/UI` · on-site, hybrid, remote · areas
`medios-editorial-y-artes-graficas`, `digital` · family `design_creative` ·
floor 19,000 €. In our tests the public boards had none: this is a profession
for LinkedIn, InfoJobs and your own list of studios' career pages.

### Engineering, science and building

**Industrial engineering** — titles: `ingeniero industrial, ingeniero de
procesos, ingeniero de calidad, técnico de calidad, ingeniero de producción` ·
on-site, hybrid · areas `ingenieria-y-produccion`, `calidad-id-prl-y-medio-ambiente` ·
family `engineering` · floor 24,000 €. Add large employers' career pages under
*Company career boards* (their domain is enough).

**Architecture** — titles: `arquitecto, arquitecta, delineante, proyectista,
BIM` · on-site, hybrid · area `construccion-e-inmobiliaria` ·
family `construction_property` · floor 20,000 €.

**Chemistry** — titles: `químico, química, técnico de laboratorio, analista
de laboratorio, técnico de calidad` · on-site · areas
`calidad-id-prl-y-medio-ambiente`, `ingenieria-y-produccion` ·
family `science_research` · floor 20,000 €.

**Laboratory technician (vocational)** — titles: `técnico de laboratorio,
analista de laboratorio, técnico de calidad, auxiliar de laboratorio` · on-site ·
area `calidad-id-prl-y-medio-ambiente` · family `science_research` · floor 20,000 €.

### Trades and hospitality

**Electrician** — titles: `electricista, oficial electricista, electricidad,
técnico electricista, mantenimiento eléctrico` · on-site ·
area `profesionales-artes-y-oficios` · family `manufacturing_trades` ·
floor 17,000 €. One of the best-served professions on public boards.

**Cook** — titles: `cocinero, cocinera, ayudante de cocina, jefe de partida` ·
on-site · area `hosteleria-turismo` · family `hospitality_tourism` ·
floor 16,000 €.

## Then

After the first week, look at **Insights** (which sources bring offers you
keep) and at **Filtered out** (which filter is doing the damage). A title that
brings only noise can go; a filter that drops what you would apply to can be
loosened.

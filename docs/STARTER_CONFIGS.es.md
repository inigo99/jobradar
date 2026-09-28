# Configuraciones para empezar

*[Read in English](STARTER_CONFIGS.md)*

Una primera configuración para diecinueve profesiones, para empezar a buscar el
mismo día que instalas JobRadar y ajustarla después. Salen de probar JobRadar
con perfiles de recién titulados en Navarra y Madrid, y en toda Europa (ver
[tests/fixtures/graduates/](../tests/fixtures/graduates/README.md)), así que piensan en alguien que empieza
en España; el razonamiento sirve para otros sitios, y [En toda Europa](#en-toda-europa)
cuenta qué cambia al buscar fuera.

Todo lo que sigue se configura en el panel —**Configuración → Qué buscas**,
**Filtros** y **Dónde buscar**— o en un `settings.yaml` que se carga con
`jobradar init --config settings.yaml` (referencia completa en
[CONFIGURATION.md](CONFIGURATION.md), en inglés).

## Lo que marca la diferencia

Casi todas las búsquedas que no encuentran nada no es que no haya ofertas: es
que las piden con palabras que los anuncios no usan, o en sitios que no las
publican.

1. **Los puestos, con las palabras que los anuncios ponen en el título.** De
   lo que devuelve cada portal solo se conserva lo que tiene un título que
   coincide con alguno de los tuyos, así que escribe lo que escribe quien
   contrata: «abogado», «jurídico», «enfermera», «electricista»; no «Consultor
   Legal Tech» ni «Director de Residencia Universitaria». El género y el plural
   dan igual («enfermera» encuentra «Enfermero/a»). Con cuatro a ocho puestos
   basta.
2. **Deja vacías las palabras clave adicionales** al principio. Cada una es
   una búsqueda más en cada portal, y las palabras generales («APPCC»,
   «Hospitality Management») traen ruido, no ofertas.
3. **Añade como portales las páginas del área de tu profesión.** Los servicios
   públicos y EURES publican pocas ofertas de algunos campos (derecho,
   marketing, diseño, ingeniería) y de algunas regiones (Navarra). La página de
   un portal para un área en una provincia lista justo lo que buscas. En
   Infoempleo la dirección es
   `https://www.infoempleo.com/trabajo/area-de-empresa_<área>/en_<provincia>/`,
   con el área que se indica en cada profesión y la provincia como la escribe
   Infoempleo (`navarra`, `madrid`, `barcelona`…). Añade también la búsqueda
   del Sistema Nacional de Empleo, que cubre todas las comunidades:
   `https://www.sistemanacionalempleo.es/OfertaDifusionWEB/busquedaOfertas.do?modo=continuar&palabraBusqueda={query}&botonNavegacion=Enviar`.
   Más en [PORTALS.md](PORTALS.md).
4. **Tu zona, y si es un límite.** Pon tu ciudad en *Zonas donde te vale
   híbrido o presencial*. Marca *Solo en estas zonas, no en el resto de mi
   país* si no te mudarías: las ofertas de otros sitios van a *Filtradas* en
   vez de al tablero. Añade *Remoto* a las modalidades si tu profesión lo
   permite.
5. **Años de experiencia: que decida tu CV.** Deja activado *Tomar el máximo
   de las fechas de mi CV, para que suba solo*, con un margen de 1 año. Las
   ofertas que piden un poco más de lo que tienes quedan aparte, «por poco»,
   en *Filtradas*; para un recién titulado suele merecer la pena escribirles
   directamente.
6. **Salario: déjalo vacío, o usa el mínimo que se indica.** Solo un salario
   publicado descarta una oferta; una estimación nunca. Los mínimos son el
   extremo inferior de la banda junior que usa JobRadar para esa familia, una
   referencia para España: súbelos si conoces tu mercado.
7. **Ofertas de hasta 30 días** al empezar (los servicios públicos publican
   despacio), y de 7 a 14 cuando ya busques a diario.
8. **LinkedIn, InfoJobs e Indeed** tienen la mayoría de las ofertas del sector
   privado en derecho, marketing, diseño e ingeniería. Vienen desactivados:
   activarlos es decisión tuya según las condiciones de cada sitio (ver
   [SOURCES.md](SOURCES.md)).
9. **Busca como mucho una vez al día.** Los portales públicos limitan a los
   lectores automáticos; si uno rechaza las peticiones, la búsqueda lo avisa y
   ese día faltan sus ofertas.

## Un ejemplo completo

Enfermería, en Pamplona, sin mudarse:

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
  min_salary:                     # vacío: sin filtro de salario
  use_profile_years: true
  years_margin: 1.0
  max_age_days: 30

sources:
  enabled: [eures, portals]       # añade linkedin, infojobs, indeed si así lo decides
  portals:
    - {name: Sistema Nacional de Empleo, url: "https://www.sistemanacionalempleo.es/OfertaDifusionWEB/busquedaOfertas.do?modo=continuar&palabraBusqueda={query}&botonNavegacion=Enviar"}
    - {name: Infoempleo — sanidad en Navarra, url: "https://www.infoempleo.com/trabajo/area-de-empresa_sanidad-salud-y-servicios-sociales/en_navarra/"}

families:
  healthcare: {priority: 1.3}     # tu campo, primero en el tablero
```

Para otra profesión, cambia los puestos, el área de Infoempleo, las
modalidades y la familia según su entrada.

## Por profesión

Cada entrada da los **puestos** que buscar, las **modalidades** que merece la
pena aceptar, el **área de Infoempleo** (para la dirección de arriba), la
**familia de empleo** que poner primero y un **salario mínimo** si quieres uno.

### Salud

**Enfermería** — puestos: `enfermera, enfermero, enfermería` · presencial ·
área `sanidad-salud-y-servicios-sociales` · familia `healthcare` · mínimo 20.000 €.
Hospitales y residencias publican también en los servicios públicos; EURES y el
Sistema Nacional de Empleo los encuentran bien en Madrid, mucho menos en Navarra.

**Fisioterapia** — puestos: `fisioterapeuta, fisioterapia` · presencial ·
área `sanidad-salud-y-servicios-sociales` · familia `healthcare` · mínimo 20.000 €.

**Psicología** — puestos: `psicólogo, psicóloga, psicólogo sanitario` (añade
`técnico de selección` si aceptarías recursos humanos) · presencial, híbrido ·
área `sanidad-salud-y-servicios-sociales` (y `recursos-humanos`) ·
familia `healthcare` · mínimo 20.000 €.

**Odontología** — puestos: `odontólogo, dentista, odontología` · presencial ·
área `sanidad-salud-y-servicios-sociales` · familia `healthcare` · mínimo 20.000 €.
En nuestras pruebas los portales públicos no tenían ofertas de dentista ni en
Navarra ni en Madrid: mira InfoJobs, Indeed y las webs de las clínicas.

**Higiene bucodental** — puestos: `higienista dental, higienista bucodental,
auxiliar de clínica dental` · presencial · área `sanidad-salud-y-servicios-sociales` ·
familia `healthcare` · mínimo 20.000 €.

### Educación y social

**Magisterio (primaria)** — puestos: `maestro, maestra, profesor de primaria,
profesor de inglés` · presencial · área `educacion-formacion` ·
familia `education` · mínimo 18.000 €. Las plazas públicas van por
oposición: añade los feeds del BOE de [PORTALS.md](PORTALS.md).

**Trabajo social** — puestos: `trabajador social, trabajadora social,
educador social, integrador social` · presencial ·
área `sanidad-salud-y-servicios-sociales` · familia `care_social` · mínimo 17.000 €.

### Derecho y empresa

**Abogacía** — puestos: `abogado, jurídico, jurista, derecho, protección de
datos, compliance, asistente jurídico` · presencial, híbrido, remoto ·
área `legal` · familia `legal` · mínimo 20.000 €. Probado en Madrid: con estos
puestos y la página del área legal, una búsqueda que no encontraba nada
encontró cuatro ofertas, la mejor con un 98 % de encaje. Añade el tablón del
Colegio de Abogados de tu ciudad si lo tiene ([PORTALS.md](PORTALS.md) incluye
el de Pamplona).

**Administración y Dirección de Empresas (ADE)** — puestos: `analista
financiero, contable, controller, administración, auxiliar contable` ·
presencial, híbrido · áreas `banca-finanzas-y-seguros`, `administracion-de-empresas` ·
familia `finance_accounting` · mínimo 20.000 €.

**Administración y finanzas (FP)** — puestos: `administrativo, auxiliar
administrativo, administrativo contable, contable` · presencial, híbrido ·
área `administrativos-y-secretariado` · familia `administration_office` ·
mínimo 16.000 €.

### Comunicación y diseño

**Marketing** — puestos: `marketing, marketing digital, community manager,
SEO, redes sociales` · presencial, híbrido, remoto ·
área `marketing-publicidad-y-rrpp` (y `digital` donde exista, como en Madrid) ·
familia `marketing_communication` · mínimo 18.000 €.

**Periodismo** — puestos: `periodista, redactor, redactora, comunicación,
community manager` · presencial, híbrido, remoto · áreas
`medios-editorial-y-artes-graficas` (Madrid), `marketing-publicidad-y-rrpp` ·
familia `marketing_communication` · mínimo 18.000 €.

**Diseño gráfico** — puestos: `diseñador gráfico, diseñadora gráfica, diseño
gráfico, maquetador, UX/UI` · presencial, híbrido, remoto · áreas
`medios-editorial-y-artes-graficas`, `digital` · familia `design_creative` ·
mínimo 19.000 €. En nuestras pruebas los portales públicos no tenían ninguna:
es una profesión para LinkedIn, InfoJobs y tu propia lista de páginas de empleo
de estudios.

### Ingeniería, ciencia y construcción

**Ingeniería industrial** — puestos: `ingeniero industrial, ingeniero de
procesos, ingeniero de calidad, técnico de calidad, ingeniero de producción` ·
presencial, híbrido · áreas `ingenieria-y-produccion`,
`calidad-id-prl-y-medio-ambiente` · familia `engineering` · mínimo 24.000 €.
Añade las páginas de empleo de las grandes empresas en *Company career boards*
(basta con su dominio).

**Arquitectura** — puestos: `arquitecto, arquitecta, delineante,
proyectista, BIM` · presencial, híbrido · área `construccion-e-inmobiliaria` ·
familia `construction_property` · mínimo 20.000 €.

**Química** — puestos: `químico, química, técnico de laboratorio, analista de
laboratorio, técnico de calidad` · presencial · áreas
`calidad-id-prl-y-medio-ambiente`, `ingenieria-y-produccion` ·
familia `science_research` · mínimo 20.000 €.

**Técnico/a de laboratorio (FP)** — puestos: `técnico de laboratorio,
analista de laboratorio, técnico de calidad, auxiliar de laboratorio` ·
presencial · área `calidad-id-prl-y-medio-ambiente` · familia `science_research` ·
mínimo 20.000 €.

### Oficios y hostelería

**Electricista (FP)** — puestos: `electricista, oficial electricista,
electricidad, técnico electricista, mantenimiento eléctrico` · presencial ·
área `profesionales-artes-y-oficios` · familia `manufacturing_trades` ·
mínimo 17.000 €. Una de las profesiones mejor cubiertas por los portales
públicos.

**Cocina (FP)** — puestos: `cocinero, cocinera, ayudante de cocina, jefe de
partida` · presencial · área `hosteleria-turismo` · familia `hospitality_tourism` ·
mínimo 16.000 €.

## En toda Europa

Buscando con los puestos en inglés de la [guía en inglés](STARTER_CONFIGS.md)
en todos los países de EURES, en septiembre de 2026, las diecinueve
profesiones encontraron ofertas —412 en total, sobre todo en Alemania, Países
Bajos, Malta, Chipre, Irlanda y Bélgica—. Lo que enseñó:

- **Dónde está cada profesión.** Trabajo social, cocina, administración y
  magisterio encuentran más ofertas junior (Países Bajos, Malta, Chipre);
  fisioterapia y psicología, en Alemania y Países Bajos; ingeniería, en
  Alemania, Austria y Suecia. Odontología es la excepción: las pocas ofertas
  estaban en francés, en Francia y Suiza.
- **Un título en inglés no es un anuncio en inglés.** Muchas ofertas alemanas
  ponen el título en inglés y el texto en alemán («Quality Engineer (m/w/d)»).
  Mira el idioma del anuncio antes de contar con él.
- **Deja apagados los tablones de remoto en profesiones presenciales.**
  RemoteOK, We Work Remotely y Himalayas responden a «lawyer» o «architect» con
  puestos como «Founder's Office» o «Solutions Architect»; solo merecen la pena
  en marketing, periodismo y diseño, y si trabajarías en remoto.
- **La mayoría pide de 3 a 5 años.** Deja que tu CV marque el máximo: esas
  ofertas van a *Filtradas* y se quedan las que piden uno o dos.
- **Deja el salario vacío.** Los mínimos de arriba son para España.
- **Algunos puestos traen otro oficio.** «CAD technician» trae CAD mecánico,
  «support worker» cuidado de personas y «designer» a secas diseño de placas y
  de producto; por eso no se sugieren. «Compliance» y «data protection» siguen
  trayendo comercio exterior e informática a un abogado: sáltalas en el tablero.

```yaml
search:
  titles: [social worker, case worker, youth worker]
  languages: [en]
filters:
  work_modes: [onsite, hybrid]
  home_country: ES
  eligible_countries: [NL, BE, IE, MT, CY, DE, AT]   # los países a los que te mudarías
  local_only: false
sources:
  enabled: [eures]
```

## Después

Pasada la primera semana, mira **Análisis** (qué fuentes traen ofertas que
conservas) y **Filtradas** (qué filtro está haciendo el daño). Un puesto que
solo trae ruido se puede quitar; un filtro que descarta ofertas a las que
aplicarías se puede aflojar.

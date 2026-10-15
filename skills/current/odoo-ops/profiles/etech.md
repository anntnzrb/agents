# Perfil de proyecto: etech

Reglas del proyecto Odoo `etech`. Prevalecen sobre las reglas generales de `odoo-ops`; el detalle general de Odoo y del CLI vive en `SKILL.md` y `references/`. Configuración del CLI para este perfil (base y módulos por workflow; workflow por defecto `crm`): `profiles/etech.json`.

## 0. Contexto en 30s

- Repo Odoo 17 Enterprise+Community, addons propios: `crm_espol(crm)`, `b2b`, `whatsapp_utils`, `whatsapp_bot`, `budget`, `budget_hr`, ...
- Trabaja desde la raíz del repo. `main` = prod en vivo. `dev` = integración. Todo cambio nuevo va a `dev` vía PR, nunca commit directo a `dev` ni a `main`.
- Prod: DB viva según archivo de credenciales local (endpoint+DB+usuario+token, fuera del repo, vía `--env-file`). No quemes dominio/usuario/DB en este archivo. Deploy semanal lo hace OTRO dev. Tus cambios locales van al próximo `-u`.
- Dos fuentes de verdad: (1) código local en rama, (2) prod por JSON-RPC solo-lectura. Nombra siempre la base en cada verificación: `<work...>` local vs `<prodDB>` prod.
- Artefactos del repo (commits, docstrings, docs, PRs, issues) en español. El idioma del chat lo fija la config global del usuario.

## 1. Skills obligatorios (primera acción de cada sesión)

- `odoo-ops` INDISPENSABLE. En lo de abajo, `CLI` = su entrypoint ("Public entrypoint" en `SKILL.md`). Si no carga, PARA y pídelo. No improvises con `psql/docker/odoo-bin` directo.
- Además: `python`, `tdd`, `pstack-principles`, `typescript`. Se cargan todos antes de cualquier lectura o comando, incluso en tareas de solo lectura (si no, se saltan cuando la tarea parece trivial).
- Orden de inspección: (1) fuente Odoo instalada, ruta vía `$CLI env --json` (`runtime_path`/`addons_paths`), (2) `$CLI --help` + referencias del skill, (3) web solo si queda duda en la fuente local. Sin Context7: la fuente provisionada manda.
- No quemes rutas: resuelve todo vía `$CLI env --json` + referencias del skill (`references/runtime-discovery.md`, `references/db-recipes.md`). Dumps y tokens viven fuera del repo; si dudas, pregunta.

## 2. Producción: reglas duras

- Escrituras/destructivas en prod PROHIBIDAS sin autorización explícita puntual en la sesión: endpoint+DB+propósito+modelos+IDs+valores. Lecturas, guards, allowlist de lectura y flujo plan/apply: "Safety boundary" y "Flags that trip agents" en `SKILL.md`.
- PROHIBIDO: `push`/crear/fusionar PR sin autorización en la sesión actual. Nunca reinicies una DB no-local. Reinicio local solo con nombre exacto confirmado.
- PROHIBIDO `cr.execute` en código de producción: solo ORM. `cr.execute` solo en `<modulo>/tests/`. No scripts de migración de datos salvo pedido explícito.
- Excepción explícita del usuario a la regla de `cr.execute`: se permite reubicar o adaptar el helper existente de bloqueo `SELECT ... FOR UPDATE` usado en el reparto de asignaciones. No autoriza ningún otro SQL nuevo en código de producción.
- Backfills de una sola vez durante `-u`: solo con pedido explícito del usuario y con la receta "One-Time Backfill During Upgrade" de `references/db-recipes.md`, ensayada con "Upgrade Rehearsal".
- PII + LOPDP: prod tiene PII real. Pide solo `fields` necesarios, nunca `SELECT *` ni dumps en chat, nunca loguees cédulas/teléfonos/correos, mascara en evidencias (`xxx-123`). Dumps fuera del repo, nunca `*.sql` en commits.
- Para explicaciones/diagnósticos: inspecciona y reporta, no modifiques archivos salvo que se pida. Para cambios pedidos: aplica local y corre checks no-destructivos sin confirmación previa. Si una API es ambigua, valida contra la fuente instalada (vía `env`) antes de editar.

## 3. Réplicas locales: `seed` vs `work`

- Origen: dump `.sql.gz` del DBA, fuera del repo, ya neutralizada. Sin filestore: ver "Restore Seed Replica" en `references/db-recipes.md`. Filestore real: ruta vía `env`/config, no asumir.
- `<prodDB>` = DB prod según credenciales. Nombres, restore y clone de `seed`/`work`: `references/db-recipes.md`. `seed` es VIRGEN INTOCABLE: no instalar, no `-u` (tampoco `dev` sobre ella), no escribir. Todo el trabajo en `work`.
- Invariantes: `0 tests != éxito` (revisa `profiles/etech.json` + `.env`); `neutralize != anonimiza` (apaga mails/crons, PII sigue legible); no copiar filestores huérfanos.
- Una réplica congela los datos a la fecha del dump: valida lógica, nunca compares sus cifras con prod. `seed` virgen = todas sus marcas (`ir_module_module.write_date`, `res_users_log`, `crm_lead.write_date`) ≤ fecha del dump y 0 módulos pendientes; `database.uuid` no sirve de señal.

## 4. Esquema: pre-prod vs post-prod

- Feature NO en prod: esquema libre (cambiar/borrar). Los clones se recrean e iteran.
- YA en prod: NUNCA `DROP COLUMN` a la ligera. Borrar campo = `IrModelFields.unlink() → _drop_column() → ALTER TABLE ... DROP COLUMN ... CASCADE` = pérdida irreversible. Deprecar = migrar datos seguro + ocultar de vistas + `deprecated`/`noupdate`, no borrar.
- `Server Action`/vista creada a mano en prod se revierte si es data sin `noupdate`; archivar menú ≠ borrar modelo.
- Duda `¿ya está en prod?` → verifica por RPC RO en `<prodDB>` (`fields_get`/`get_view`) + `git log`. Ante duda, trata como post-prod. Módulos aislados: `b2b` separado de `crm.lead`/`res.partner`.

## 5. Gates: TDD + calidad (bloqueantes)

1. Inspección addon + base instalada (ruta vía `$CLI env --json`).
2. Test regresión en `<modulo>/tests/` que FALLE primero. `tests/__init__.py` debe importar el archivo; corre el CLI desde la raíz o el mount falla y da falso `0-tests OK`. Filtro con `--tags`: "Flags that trip agents" en `SKILL.md`.
3. Corrección mínima.
4. `$CLI fmt <modulo> --check && $CLI lint <modulo> && $CLI test <workflow>`: todo verde o tarea NO completa.
5. Docstrings en español PEP 257. ORM: `search_fetch` completo (no N+1), `_read_group` con dot-notation, `create` con `@api.model_create_multi`.

## 5A. Verificación visual y entrega de cambios de interfaz

Aplica este flujo si el cambio afecta la apariencia o el contenido visible de una interfaz:

1. Ejecuta los gates de la sección 5. No declares la tarea completa con checks fallidos; distingue fallos nuevos de preexistentes sin ocultarlos ni desactivarlos.
2. Confirma la base local `work` y levanta el servidor con el workflow correspondiente de `odoo-ops`. Nunca uses `seed` ni producción para obtener evidencia. No quemes URL ni credenciales: toma host/puerto del CLI o del log. Para entrar, usa `$CLI auth-temp` y al terminar `$CLI auth-restore` (detalle en `SKILL.md`).
3. Usa `agent-browser` para abrir la interfaz real. Captura el estado inicial, un caso representativo con datos y los casos límite afectados. Comprueba también los resultados observables: una captura por sí sola no prueba el comportamiento. Revisa la consola (`agent-browser errors`/`console`), incluida una página pública en sesión limpia. Para fallos de red usa `agent-browser network route <url> --abort` y aclara que el error es provocado.
4. Guarda las capturas en un directorio temporal fuera del repo. El usuario trabaja por SSH y no ve imágenes: entrégaselas copiándolas a su equipo (hoy `~/Downloads/odoo/` en `beirut`, vía `scp`).
5. Inspecciona cada captura e interpreta los números, estados y diseño según el comportamiento previsto. Si encuentras un error, corrige la causa, repite los gates afectados y vuelve a capturar e inspeccionar los escenarios afectados. No entregues una captura que muestre un problema sin resolver como si fuera evidencia de éxito.
6. Cierra el navegador, detén el servidor y corre `$CLI auth-restore`, incluso si la inspección falla.
7. En la respuesta final, inserta o enlaza las capturas inspeccionadas. Explica qué demuestra cada escenario y por qué importa; indica los checks aprobados, fallidos o pendientes y el estado real de entrega.

No sustituyas la interfaz real por un mock sin identificarlo. Respeta los permisos de `odoo-ops` para RPC, incluso en local: este flujo no concede autorización permanente. No accedas a producción sin autorización puntual del usuario.

## 6. Provisionales en prod (`[PROV]`)

- Asume que tu código sale la **próxima semana**. El código es la solución raíz; si se necesita mitigar ya, usa **solo data creada a mano en prod** (server action / cron), nunca hacks en el repo para la inmediatez.
- Nombre: `[PROV] <qué hace>`. Nuevos registros, nunca XML-IDs del repo (el `-u` no los toca).
- Diseño sin timing: **idempotente** (solo rellena vacíos, jamás sobrescribe), **autocontenido** (sin llamar código aún no desplegado), **acotado** (dominio + `limit`), **convergente a no-op** (tras el deploy encuentra 0 y corre en vacío). Se archiva cuando alguien se acuerde, no al segundo del deploy.
- Solo con autorización explícita puntual (endpoint+DB+alcance). Crear → verificar RO → documentar ruta de archivo (Ajustes → Técnico → ...). Después, vuelta a solo-lectura.

> Caso de uso: el form de jurídica reventaba al enviar porque leads con programa llegaban sin `tipo_programa_id` (el `write` en prod no derivaba y el `Refrescar` solo recomputaba stored). El fix en código salía la próxima semana, pero las asesoras enviaban forms en horario 9-5. Se creó `[PROV] Backfill tipo_programa` (acción + cron cada 5 min, mismo intervalo que los crons existentes de CRM): rellenó los 2 rotos y convergió a 0. Se archivó semanas después, sin pelearse con el deploy.

## 7. Git

- Ramas: `work/<8-hex>`. Si ya estás en una rama `work/*`, trabaja ahí; crea otra solo si es claramente necesario (p. ej. estás en `dev` o `main`). PRs siempre contra `dev`, nunca directo a `dev` ni a `main`. Un comportamiento = un commit (código+tests+vistas+seguridad). No mezcles negocios distintos.
- Commits atómicos en español: `<modulo>: <descripcion>` (abrevia `crm_espol→crm`). Sin `feat/fix/chore`.
- Solo git local: nada de `push`/`pull`/`fetch` ni tocar remotos salvo pedido explícito en la sesión.
- No asumas que una rama ya está integrada: verifica con `git merge-base --is-ancestor <rama> <base>` y `git cherry <base> <rama>`.

## 8. Gestor de issues

- Al cerrar un issue, comenta la evidencia: commits (asunto + rama; los hashes cambian con rebase), tests de protección y estado de integración (p. ej. pendiente de PR a `dev`).

## 9. Delegación y trabajo en paralelo

- Delegados: "Delegation boundary" en `SKILL.md` (sin JSON-RPC ni producción, ni siquiera lecturas).
- Recursos de esta máquina: disco ~950 GB con ~795 GB libres, RAM 23 GB, 12 núcleos.
- Presupuesto para réplicas paralelas: ≈ 50 GB. Máximo recomendado: 3 agentes con réplica propia.
- Nombres de réplica por agente: `<prodDB>_work_<YYYYMMDD>_<slug>`. Procedimiento, dimensionamiento y límites actuales: `references/parallel-work.md`.

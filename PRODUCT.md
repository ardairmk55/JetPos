# POSHANE — Product context

> Inferred from the user's redesign brief (no interview run; assumptions labelled).

**Register:** product (Operate mode). App UI, not a marketing surface.

**What it is:** Commercial restaurant POS and operations software (tables, tickets, kitchen display, cash, stock, CRM, reports) for restaurants, cafes, breakfast halls and municipal social facilities in Turkey. Local-network first, works offline.

**Users and scenes**
- Waiter on a phone/tablet in a busy dining room: enters orders in seconds, one-handed, glare and noise.
- Cashier on a 1024x768 / 1366x768 touch PC: takes payments, splits bills, closes the day; mistakes cost money.
- Kitchen staff on a wall-mounted screen, read from 2 m, wet/greasy hands.
- Owner / manager on a laptop: reports, stock, staff, settings, at the end of the day.
- Platform/support staff: licences, tickets, health.

**Brand:** POSHANE, tagline "Hızlı Servis, Akıllı Yönetim." Colours fixed by the owner: anthracite `#252936`, orange `#F28C28`, light canvas `#F5F6F8`, plus white and neutrals. Orange is scarce: primary actions, active state, brand mark only.

**Personality:** professional, calm, quick, trustworthy. Closer to Toast / Lightspeed / Square operational density than to a generated analytics dashboard. (Assumption: dense-but-calm, 14 px base text.)

**Anti-references:** gradients, glass/blur, heavy shadows, pill-rounded cards, emoji used as icons, a different colour on every widget, decorative charts, oversized headings, coloured left-border cards.

**Constraints:** Vanilla JS + Tailwind 3 + Django templates; no CDN (LAN offline, fonts/icons self-hosted); Turkish default, English secondary; touch targets >= 44 px; WCAG AA contrast; light and dark theme; do not break any API/flow.

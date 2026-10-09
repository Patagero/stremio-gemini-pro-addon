# Slo AI Gemini 3.7 Pro Prevajalnik za Stremio

Ločen in samostojen Stremio vtičnik za vrhunsko samodejno prevajanje podnapisov v slovenščino z uporabo najnovejšega modela **Google Gemini 3.7 Pro**.

## Glavne značilnosti
1. **Prioriteta vira:** Italijanščina (`it` / `ita`) &rarr; Angleščina (`en` / `eng`).
2. **Čiščenje SDH:** Samodejno odstranjevanje zvočnih opisov, oklepajev `[...]`, `(smeh)` in oznak govorcev.
3. **IMDb & Cinemeta analiza:** Zaznavanje filmskega žanra (Sci-Fi, Crime, Comedy, Horror, Romance...) za dinamično prilagoditev besednega zaklada in slenga.
4. **Spolno ujemanje (ona/on):** Natančna analiza spola likov ter pravilna raba glagolskih oblik in dvojine.
5. **Omejitev bralne hitrosti:** Največ 2 kratki vrstici na podnapis (do 42 znakov na vrstico), prilagojeno za TV zaslone.
6. **Popolna SRT integriteta:** Natančno ohranjeni časovni žigi in številčenje.

## Namestitev v Stremio
Po namestitvi na Render v Stremio dodajte URL manifesta:
```text
https://YOUR-RENDER-SERVICE.onrender.com/manifest.json
```

## Render namestitev
1. Povežite ta GitHub repozitorij na [Render.com](https://render.com).
2. Ustvarite nov **Web Service** (izberite Docker runtime).
3. V nastavitvah (Environment) dodajte spremenljivke:
   - `GEMINI_API_KEY`: Vaš Google Gemini API ključ
   - `GEMINI_MODEL`: `gemini-3.7-pro`
   - `PUBLIC_BASE_URL`: URL vašega Render servisa (npr. `https://stremio-gemini-pro-addon.onrender.com`)

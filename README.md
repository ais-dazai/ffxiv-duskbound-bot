# Bot Discord: ruoli automatici per gli Ultimate di FFXIV

Questo bot permette agli utenti del tuo server Discord di:
1. `/registra` — collegare il proprio personaggio FFXIV (verifica tramite Lodestone)
2. `/verifica` — confermare che il personaggio è davvero suo
3. `/aggiorna-ruoli` — controllare su FFLogs quali Ultimate ha clearato e ricevere in automatico i ruoli corrispondenti (es. "Cleared - Dragonsong's Reprise (Ultimate)")

Non serve toccare KupoBot: questo è un bot separato, dedicato solo a questa funzione.

---

## Cosa ti serve prima di iniziare

Ti servono 3 cose, tutte gratuite:

1. **Un bot Discord** (creato dal Developer Portal di Discord)
2. **Delle credenziali FFLogs** (Client ID + Client Secret)
3. **Un account Railway** (per ospitare il bot online 24/7)

Segui i passaggi in ordine, con calma. Se qualcosa non torna, fermati e chiedimelo pure.

---

## Passo 1 — Crea il bot su Discord

1. Vai su https://discord.com/developers/applications e fai login.
2. Clicca **New Application**, dagli un nome (es. "FFXIV Ultimate Roles").
3. Nel menu a sinistra vai su **Bot** → **Add Bot**.
4. In questa pagina:
   - Attiva **Server Members Intent** (è fondamentale, senza il bot non funziona).
   - Clicca **Reset Token** e copia il token che appare. Questo è il tuo `DISCORD_TOKEN`: tienilo segreto, non condividerlo mai con nessuno.
5. Nel menu a sinistra vai su **OAuth2 → URL Generator**:
   - In "Scopes" seleziona `bot` e `applications.commands`.
   - In "Bot Permissions" seleziona almeno: `Manage Roles`, `Send Messages`, `Use Slash Commands`, `Read Message History`.
   - Copia il link generato in fondo alla pagina e aprilo in una nuova scheda: ti porterà a scegliere in quale server invitare il bot.
6. **Importante**: dopo aver invitato il bot, vai nelle **Impostazioni server → Ruoli** e trascina il ruolo del bot **in alto**, sopra a dove verranno creati i ruoli "Cleared - ...". Un bot non può assegnare ruoli che stanno più in alto di lui nella gerarchia.

---

## Passo 2 — Ottieni le credenziali FFLogs

1. Vai su https://www.fflogs.com/api/clients/ e fai login con il tuo account FFLogs (creane uno gratuito se non ce l'hai).
2. Clicca **Create Client**.
3. Dagli un nome qualsiasi (es. "ruoli-discord"), come Redirect URL puoi mettere `https://localhost` (non verrà mai usata per questo tipo di bot).
4. Salva e copia **Client ID** e **Client Secret**: ti serviranno per `FFLOGS_CLIENT_ID` e `FFLOGS_CLIENT_SECRET`.

---

## Passo 3 — Metti il bot online con Railway

1. Vai su https://railway.app e crea un account (puoi accedere anche con GitHub).
2. Nella dashboard, clicca **New Project**.
3. Scegli **Empty Project**, poi **+ New → Empty Service** (oppure "Deploy from GitHub" se preferisci prima caricare questi file su un repository GitHub — se non sai come fare, usiamo la via più semplice sotto).
4. Il modo più semplice se non conosci GitHub:
   - Vai su https://github.com, crea un account gratuito se non ce l'hai.
   - Crea un nuovo repository (es. "ffxiv-ultimate-bot"), pubblico o privato indifferente.
   - Carica tutti i file di questa cartella (bot.py, ffxiv_api.py, storage.py, requirements.txt) usando il pulsante **"Add file → Upload files"** sul sito di GitHub (si trascinano e basta, nessun comando da digitare). **Non caricare il file `.env`** se lo crei — le chiavi vanno inserite solo su Railway, mai su GitHub.
   - Torna su Railway → **New Project → Deploy from GitHub repo** → seleziona il repository appena creato.
5. Railway rileverà automaticamente che è un progetto Python e proverà a fare il deploy.
6. Vai nella scheda **Variables** del servizio su Railway e aggiungi queste variabili (una per una, con **Add Variable**):
   - `DISCORD_TOKEN` → il token copiato al Passo 1
   - `FFLOGS_CLIENT_ID` → dal Passo 2
   - `FFLOGS_CLIENT_SECRET` → dal Passo 2
   - `XIVAPI_KEY` → lascialo vuoto per ora (vedi nota sotto)
7. Railway rifarà automaticamente il deploy dopo aver salvato le variabili. Vai nella scheda **Deployments → View Logs**: se vedi scritto `Bot connesso come ...` è tutto ok, il bot è online.

---

## Passo 4 — Prova i comandi su Discord

Sul tuo server, digita `/` in una chat: dovresti vedere `/registra`, `/verifica`, `/aggiorna-ruoli` tra i comandi disponibili (potrebbero metterci qualche minuto ad apparire la prima volta).

Prova tu stesso il flusso completo prima di annunciarlo alla community:
1. `/registra nome:"Nome Cognome" server:"Odin"`
2. Metti il codice ricevuto nella bio del Lodestone
3. `/verifica`
4. `/aggiorna-ruoli`

---

## Nota su XIVAPI (verifica del Lodestone)

Il bot usa https://xivapi.com per cercare il personaggio e leggerne la bio. Questo servizio di terze parti (non ufficiale, gestito dalla community) a volte cambia condizioni d'uso o richiede una chiave gratuita. Se durante il test `/registra` o `/verifica` restituiscono errori:
1. Vai su https://xivapi.com e controlla se serve registrarsi per ottenere una `private_key`.
2. Se sì, creala e incollala nella variabile `XIVAPI_KEY` su Railway.
3. Se il sito è cambiato più profondamente, scrivimi cosa vedi (screenshot o messaggio di errore) e sistemiamo insieme il codice: le API di terze parti cambiano di tanto in tanto, è normale.

---

## Cose da sapere

- **I ruoli si chiamano automaticamente** "Cleared - [nome del fight]" (es. "Cleared - The Omega Protocol (Ultimate)") e vengono creati da soli al primo utilizzo, non serve crearli a mano.
- **I dati dei personaggi registrati** sono salvati in un file `data.json` dentro al progetto. Su Railway questo file resta finché non fai un nuovo deploy da zero — per una community grande, in futuro vale la pena passare a un vero database, ma per iniziare va benissimo così.
- **FFLogs registra solo le kill**, non i wipe: quindi un clear = un log presente per quel fight. Se un giocatore non carica mai un log della kill (raro, ma capita), il bot non lo vedrà come "clearato" anche se in game ha ottenuto il titolo/achievement.
- Se in futuro esce un nuovo Ultimate, non serve modificare il codice: il bot lo troverà da solo tra le zone "Ultimate" di FFLogs.

Se ti blocchi in un punto qualsiasi, scrivimi esattamente cosa vedi e ti aiuto a sbloccarlo.

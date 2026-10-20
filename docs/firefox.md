# Firefox add-on

Optional. The workbench and the command line fill a library without it.
Load it only when you want to save from a page you already have open.

Zotero's Connector remains the way to save a page straight into Zotero.
This add-on does the same gesture for the folder copy on this computer
(`out/`). Keep the Connector. Skip this one if you never want a second
toolbar button.

The toolbar button uses the Paperful box mark. It reads Zotero so a paper
already in the library is not created again. It writes only the mirror. It
does not create items in Zotero, it does not attach, and it does not talk
to Zotero's connector port. **Alt+Shift+P** saves the current page. Right-click
a page, tab, or link for the same save. A badge counts tabs from the current
gaps or snowball walk that are still waiting.

## Why a browser extension

You are already on the article. The button takes what that tab can see and
puts it in the quiet mirror.

| | Zotero Connector | This add-on |
| --- | --- | --- |
| Save the page you are on | Into the Zotero library | Into `out/`, the folder copy |
| PDF already on the page | Attaches it in Zotero | Copies it into the item folder |
| No PDF on the page | Keeps an HTML snapshot in Zotero | Keeps `snapshot.html` in the item folder, and can search your configured lanes for a PDF |
| Many tabs | One page at a time | A checklist of the tabs you select, including tabs a snowball or gaps walk just opened |

The folder copy is the stable, platform-agnostic half of the library. One
`record.json` and one PDF (or snapshot) per item, in a directory you can
back up or hand to another tool. Zotero stays the catalogue that is well
tested. The bytes in `out/` do not depend on Zotero's file storage, a
particular Zotero version, or a later move to another citation manager.
[Quiet mirror](quiet-mirror.md).

What you get that the Connector does not:

- **A deeper search when the page has no PDF.** The Connector can only save
  the file the tab already shows. Tick **Search my sources** and Paperful
  runs the same lanes as `paperful run` for that one item (open access
  first, campus login when you have configured it). The PDF lands in the
  item folder. Nothing is attached until you attach it yourself.
- **Many tabs at once.** Select the tabs you want, or start from the ones a
  snowball or gaps handoff just opened. Review the plan (create, update,
  ambiguous, blocked) before anything is written. Ambiguous rows ask which
  key to keep. A walk tab matches by URL or DOI, not URL alone.
- **The same item, not a second one.** A DOI or URL that is already in
  Zotero or in the mirror updates that record. Empty fields get filled,
  including authors, year, journal, and abstract when the page names them.
  Fields you already have stay as they are.

You do not need the add-on to fill missing PDFs. **Wanted** and
`paperful run` do that from the library. The add-on is for the moment you
are looking at the paper.

## What the button does

**This page.** Detect a DOI, PDF, title, authors, year, journal, and abstract
from Highwire / Dublin Core meta tags and JSON-LD. Pick the collection for a
new item. An optional note lands in `notes/paperful-capture.html`. After a
save, open the item folder or the Wanted page when the workbench is running.

- If the DOI or URL is already in the mirror or in Zotero, fill only empty
  fields on that item. A Zotero hit keeps the Zotero key. The mirror folder
  is created from that item when it was missing.
- If both say the paper is absent, create a mirror item under
  `[extension].collection` (default `Capture`).
- If Zotero is closed and the mirror has no match, capture will not create
  an item unless you tick “Zotero didn't answer. Create a mirror item anyway?”

**Selected tabs.** A checklist of the current window, in the style of a
download queue. Tabs opened by `gaps --handoff tabs` or `--handoff walk` are
pre-checked (**From this walk**). **Review selected** plans each tab first.
Save writes only after that review. Snowball and gaps still open those tabs.
The add-on does not open them and does not start a snowball.

**PDF, or a snapshot.** A PDF the tab can already see is saved with the
browser's cookies into the drop directory, then copied into the item folder.
When the tab has no PDF, and the item does not already have one, the add-on
saves `snapshot.html` beside `record.json`. Scripts are removed before that
file is stored, so opening it later does not run the publisher page. This is
the same job as a Zotero snapshot: a copy of the page you could see, not a
promise of a publisher PDF.

**Search my sources** is off until you tick it. It runs the configured fetch
lanes for that one item, on the mirror, without attaching. It does not turn
on sources that are off in your config. Known pirate hosts are refused
before any download.

`[extension].snapshot` defaults to `auto`. Each capture refreshes `out/`
once first, including when `[mirror].refresh` is `manual`. `off` skips that
refresh. Either way, a live read runs when Zotero is open.

## Where files land

| What | Where |
| --- | --- |
| New item that is in neither place | `out/<collection>/` — the picker, or `[extension].collection` (default `Capture`) |
| PDF the tab could already open | Browser download, copied into the drop directory, then the item folder |
| Page with no PDF | `snapshot.html` in the item folder |
| Optional capture note | `notes/paperful-capture.html` |
| Tabs opened by a handoff | `state/handoff/session.json` (rows get `saved_at` after a matching update) |

The drop directory is `[extension].drop` when set, otherwise `[inbox].dir`,
otherwise `state/capture/drop`. The host will copy a just-downloaded PDF or
HTML snapshot from your user Downloads folder into that drop directory. You
can still point Firefox's download folder at the drop directory if you prefer.
Paperful still refuses a path that is not in the drop directory, Downloads, or
the inbox dir.

## Install

The add-on is unsigned. Load it as a temporary add-on. It is not on
addons.mozilla.org.

1. `paperful capture install-host`. This writes a user-level Firefox
   native-messaging manifest (macOS, Linux, or Windows). On macOS the launcher
   lives under Application Support so Firefox can execute it.
2. Firefox → `about:debugging` → This Firefox → Load Temporary Add-on →
   `extension/firefox/manifest.json`.

A temporary add-on is gone after Firefox restarts. Load it again. Options →
Test connection should say Connected, and shows the drop path (copy or open
that folder). A manifest change needs Remove, then Load Temporary Add-on
again. **Alt+Shift+P** is the save shortcut (Firefox → Add-ons → Paperful →
Manage Extension Shortcuts if it collides).

The same identity check without the browser:

```sh
paperful capture plan --doi 10.1000/example
paperful capture session
```

`plan` writes nothing. `session` prints the handoff tab list. Apply is the
add-on's confirm step; it is also `paperful capture apply` with one JSON
object on stdin. See [Commands](commands.md) and the `[extension]` keys in
[config](config.md).

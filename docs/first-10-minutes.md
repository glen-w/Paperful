# First 10 minutes

What you see the first time the workbench opens, in the words on the screen.
The workbench lands papers on this computer, then you can grow the library,
ask the PDFs you hold, and use writing help. This walkthrough is the first
fill only: no campus login, no Google Scholar, and no AI model.

You need the workbench running (`docker compose up`, then
http://127.0.0.1:8765) and Zotero open on the same computer
([Docker](docker.md), [Zotero](zotero.md)). Fetch stance:
[legal and privacy](legal-privacy.md).

## 1. Open the workbench

The first page is **Wanted**. With no collection chosen it shows a line
telling you to pick one. If Zotero is closed it says the library is down.
**System** lists what is wrong and the one next step for each row.

## 2. Pick a collection

Open **Library**. Press the target icon beside a collection. Its name
appears in the header and stays there.

## 3. Read Wanted

Back on **Wanted**, three counts sit at the top:

| Tab | What is in it |
| --- | --- |
| **Missing** | Papers in the collection with no PDF |
| **Held** | PDFs Paperful downloaded that need a look before they go into Zotero |
| **Have** | Papers that already have their PDF |

A new collection usually has rows under Missing and nothing under Held.

## 4. Preview

Tick a few Missing rows and press **Preview selected** (or **Preview all**).
Preview downloads nothing. It shows where each paper could come from.

## 5. Grab

Press **Grab selected**. The PDFs are saved to the `out/` folder on this
computer. On Zotero 10 or newer they are also attached into the library.
On Zotero 7 to 9 the files stay in `out/` and you add them in Zotero
yourself. Settings → **After Grab** can make Attach a separate button.

## 6. Find `out/` on disk

Open the folder in your file manager. With the default install it is
`paperful-out`, beside the folder you cloned. Each paper has its own folder
with the PDF inside. Open one or two and check they are the right papers.

## What next

- [First fill](first-fill.md) is the same job in full, with screenshots.
- [Grow the library](grow-library.md) adds papers on a topic.
- [Ask](rag.md) answers questions over PDFs already on disk (needs a model).
- [Tidy a collection](tidy-library.md) fixes duplicates and identifiers.

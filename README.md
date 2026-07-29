# Proposal Automation

*Public copy of an internal tool I built at VS Engineering. The code and the
workflow are real. Client data, staff names, project content and network
paths have been replaced with placeholders.*

Our proposal coordinator writes Letters of Interest for INDOT bids. Three
things ate her time: digging through a network drive for past projects and
resumes worth reusing, proofreading a finished PDF before it went out, and
never really knowing why the firm that won scored better than us. These
tools do those three things.

![Search demo](demo_data/vs-search-demo.gif)

## Try it

There's fake sample data in `demo_data/` so the whole thing runs without any
company files:

    py -m pip install -r requirements.txt
    py -m src.resumes index demo_data/resumes
    py -m src.profiles index demo_data/profiles
    py demo_data/run_demo_server.py

Open the address it prints. Search works straight away. On the LOI Tools tab,
upload `demo_data/Sample-Draft-LOI.pdf` and the checker will find the wrong
RFP number and the typos planted in it.

The AI comparison needs an Anthropic API key, so it isn't part of the demo.

## What's in it

**Search** (`src/profiles.py`, `src/resumes.py`) indexes a few thousand
project profiles and staff resumes off the shared drives and full-text
searches them. Project profiles get tagged by service, region and client from
word lists in `tags.yaml`, so you can search `trail lebanon` or `bridge
central_indiana`.

The resume template turned out to lay everything out in Word text boxes,
which python-docx reads as empty. Had to parse the raw `document.xml` for
`w:t` nodes instead.

**Mistake checker** (`src/check.py`) reads a finished LOI PDF and flags wrong
RFP or item numbers, a client name left over from a reused template, doubled
words, page-limit overruns and likely typos. It earned its keep on the first
real run: `RFP 2506` in the footer of every page of a 2605 LOI.

Spell checking a document full of Indiana place names is mostly a fight
against false positives. It flagged Fortville, Cutsinger, Waldron and ACEC and
suggested "orville", "cunninger", "caldron" and "ace". Six of eight findings
were noise, which buries the two that matter. The fix was to build the
allowlist out of the project and resume indexes the tool had already made —
those words are all over our own project write-ups, so the corpus is a better
list than one maintained by hand. Same document now reports two findings, both
real typos.

**Comparison** (`src/compare.py`) puts our LOI next to a competitor's and asks
Claude the same set of questions about each section — cover letter, project
manager, technical approach, experience, graphics. The scoring criteria go
into the prompt; the actual scores stay out, so it isn't just working
backwards from the result.

Two things worth mentioning here. Each LOI goes in as extracted text *and* as
an image of every page — without the pages you can't say anything real about
layout or exhibits, and it was reduced to inferring charts from stray
captions. Sending the PDFs directly doesn't work: ours run to 15MB of
print-resolution artwork and three of them exceed the API's 32MB request
limit, so pages get re-rendered at screen resolution first, which costs about
a megabyte and loses nothing a scorer could see.

The other thing is that both documents are sales pitches. An early version
read a competitor's claim about site conditions, concluded we'd got a fact
wrong, and recommended we drop a design item — on nothing but their say-so.
It reports disagreements as disagreements to check now.

**Review** (`src/review.py`) runs the checker and the comparison together.

Everything is on one web page (`src/web.py`) — plain `http.server`, no
framework — so nobody has to touch a command line.

## Opening a folder from a web page

The search results list a file's path on the shared drive, and the obvious
next thing to want is a button that opens that folder. This is harder than it
sounds: a browser will not follow a `file://` link from an `http://` page, and
gives JavaScript no other way to reach the desktop. There's no clever
workaround — something outside the browser has to do the opening.

So the button tries three things in order:

1. Ask the server. It compares the requester's IP against its own, and if
   you're at the machine hosting the page it opens Explorer itself. Nothing to
   install. (The first version guessed this from `location.hostname` and only
   accepted `localhost`, so anyone browsing by IP — which is the address the
   server prints on startup — got told they were remote.)
2. Hand off to a `vsfolder:` handler, on any PC where the one-time registry
   entry has been installed. `open-folder.vbs` decodes the path, refuses
   anything that isn't a real file or folder, and opens Explorer.
3. Copy the folder to the clipboard so it can be pasted into Explorer.

`Install Open Folder (all users).ps1` installs the handler for every user of a
machine, which is the version you hand to Intune or an RMM tool.
`Deploy Open Folder.ps1` pushes it to a list of computers over PowerShell
remoting. `Enable Open Folder.bat` does one user, no admin rights needed.
Nothing is ever asked of staff — a PC without the handler just falls back to
the clipboard.

## Notes

`py`, not `python`, on Windows.

`reference/` and `output/` aren't in git — that's where the real LOIs,
competitor documents and generated reports live.

Report rendering (`markdown_to_docx`, `markdown_to_html`) shares one parser so
the Word file and the web page can't drift apart.

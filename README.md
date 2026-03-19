# pdflinks

`pdflinks` is a tool which (1) extracts links from PDFs and (2) checks they are
not stalled (timeouts, HTTP 4xx/5xx, only HTTP, etc).

It is not targeting a CI pipeline usage. Most of the messages are false
positives and that is inherent with the task. Instead, it is meant to be run
from time to time, with the output checked by a human.

## Usage

```
⟩ uvx pdflinks full-audio-slides.pdf
full-audio-slides.pdf: 5s timeout: https://www.bluez.org/
full-audio-slides.pdf: skipped 'http' request: http://www.dest-unreach.org/socat/
full-audio-slides.pdf: 404 HTTP code: https://elixir.bootlin.com/linux/latest/source/sound/soc/samsung/neo1973_wm8753.c
full-audio-slides.pdf: 404 HTTP code: https://elixir.bootlin.com/linux/latest/source/Documentation/devicetree/bindings/sound/atmel-wm8904.txt
```

## How it works

 - Extract URLs from PDFs.
 - Group them up by domain.
 - Distribute domains to a few workers. A worker loops over URLs, making
   requests and reporting errors (but continuing).

Notes:
 - We start work with domains that have the most URLs. It will probably take the
   longest.
 - It is more efficient to call it once rather than N times. That way it groups
   URLs together, dedups them and doesn't wait on a trailing domain with many
   URLs.
 - The domain grouping means we never send more than one concurrent request to
   any domain. We don't sleep and don't respect `robots.txt` however.
 - We lie about our `User-Agent` to avoid being caught by Anubis & co.
 - When an error occurs, we print it once per PDF in which it appeared. That
   means grepping the output for one specific PDF works as expected.

# Binding Kind

> **Tooltip:** Whether a source_binding produces a template variable string (text) or Claude content blocks (content_blocks, e.g. PDF vision input).

## Definition

A discriminator on source_binding: `text` means the resolved value is substituted into a Jinja template variable; `content_blocks` means the resolved value is a list of Claude content blocks (image, document) prepended to the first user message. content_blocks is how Vault PDFs reach Claude as vision input.

## See also

- [Source Binding](source-binding.md)
- [Source Binder](source-binder.md)

## Source

_(no single canonical source — consult [architecture/](../architecture/))_

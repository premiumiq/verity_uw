# Web UI Design Guide

## Color Theme (from PremiumIQ PowerPoint)

### Primary Palette
| Role | Hex | Usage |
|---|---|---|
| Background | `#FFFFFF` | Page background — minimalist white |
| Text Primary | `#4D4D4D` | Body text, headings |
| Text Secondary | `#7F7F7F` | De-emphasized text, labels, metadata |
| Background Alt | `#F2F2F2` | Table striping, card backgrounds, section dividers |
| Border | `#DBDBDB` | Table borders, card borders, dividers |

### Blues (primary accent — use liberally)
| Role | Hex | Usage |
|---|---|---|
| Blue Primary | `#8FAADC` | Navigation active state, primary buttons, links, badges |
| Blue Dark | `#405A8A` | Button hover, sidebar background, emphasis |
| Blue Deep | `#2B4D8A` | Heading accents, selected states |
| Blue Light | `#D2DDF1` | Hover backgrounds, selected rows, info alerts |
| Blue Pale | `#E8EEF8` | Card backgrounds for highlighted items |

### Greys (secondary — use for structure)
| Role | Hex | Usage |
|---|---|---|
| Grey Dark | `#3A3A3A` | Sidebar text, strong labels |
| Grey Medium | `#8AB391` | — (avoid, this is green-grey) |
| Grey Light | `#C9C9C9` | Disabled states, placeholder text |
| Grey Pale | `#EDEDED` | Input backgrounds, code blocks |

### RAG Colors (sparingly — status indicators only)
| Role | Hex | Usage |
|---|---|---|
| Green | `#8AB391` | Champion status badge, passed tests, healthy |
| Amber/Gold | `#E3B447` | Staging/shadow badges, warnings, partial pass |
| Red | `#ED7D31` | Failed tests, errors, deprecated badge |

### Additional Accent
| Role | Hex | Usage |
|---|---|---|
| Purple | `#825979` | Avoid unless needed for charting distinction |

## Design Principles

1. **Minimalist white background** — no dark mode, no high contrast mode
2. **Blues dominate** — navigation, buttons, links, active states all use the blue palette
3. **Greys for structure** — borders, dividers, de-emphasized text
4. **RAG only for status** — green/amber/red only on status badges, not decorative
5. **Simple, modular, readable** — copious HTML comments, descriptive CSS class names
6. **No CSS framework complexity** — use Tailwind via CDN for utility classes, custom CSS variables for the theme. No DaisyUI (too opinionated, harder to customize to this specific palette)

## Tech Stack

- **Jinja2** — server-side HTML rendering, no frontend build step
- **HTMX** — dynamic updates without writing JavaScript
- **Tailwind CSS** via CDN — utility classes for layout
- **Custom CSS variables** — the PremiumIQ color palette defined once, used everywhere

## Code Standards for Templates

- Every HTML template must start with a comment block explaining what the page shows
- CSS classes should be descriptive: `verity-badge-champion` not `vb-c`
- Jinja2 blocks clearly labeled with comments
- No inline styles — all styling via classes
- Template inheritance: base.html → page templates

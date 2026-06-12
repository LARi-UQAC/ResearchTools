# Word → LaTeX preamble patches

Copy-pasteable LaTeX blocks for each step of the standard patch sequence applied
after `pandoc <file>.docx -o <file>.tex --extract-media="img_<file>"`.

Every block below is derived from a specific Word XML element so every value
traces back to the source. Replace `<...>` placeholders with values extracted by
`docx_inspect.py`.

---

## 1. Document class and base size

Word `<w:docDefaults><w:rPrDefault><w:sz w:val="22"/>` → 11 pt.

```latex
\documentclass[letterpaper,11pt]{article}
```

If `<w:sz>` is 24 → 12 pt, 20 → 10 pt, 28 → 14 pt.

---

## 2. Geometry (margins + paper)

Word `<w:pgMar w:top="993" w:right="1440" w:bottom="1440" w:left="1440" w:header="431" w:footer="289"/>`
→ top 0.69 in = 1.75 cm, others 1 in = 2.54 cm.

```latex
% Word: top=993 twips (0.69in = 1.75cm), L/R/B = 1in (2.54cm)
\usepackage[
  letterpaper,
  top=1.75cm,
  bottom=2.54cm,
  left=2.54cm,
  right=2.54cm,
  headheight=1.5cm,
  headsep=0.4cm,
  footskip=0.8cm
]{geometry}
```

Conversion: `cm = twips / 1440 * 2.54`.

---

## 3. Arial font (works with both pdfLaTeX and Xe/LuaLaTeX)

Word `<w:rFonts w:ascii="Arial"/>` → Helvetica (metric Arial substitute) for
pdfLaTeX, native Arial for Xe/LuaLaTeX.

```latex
\usepackage{iftex}
\ifPDFTeX
  \usepackage[T1]{fontenc}
  \usepackage[utf8]{inputenc}
  \usepackage{textcomp}
\else
  \usepackage{unicode-math}
  \defaultfontfeatures{Scale=MatchLowercase}
  \defaultfontfeatures[\rmfamily]{Ligatures=TeX,Scale=1}
\fi
\usepackage{lmodern}
% === Arial : Helvetica comme substitut métrique compatible ===
\ifPDFTeX
  \usepackage[scaled=1.0]{helvet}
  \renewcommand{\familydefault}{\sfdefault}
\else
  \setmainfont{Arial}
  \setsansfont{Arial}
\fi
```

---

## 4. Line spacing

Word `<w:spacing w:line="276" w:lineRule="auto"/>` → 276 / 240 = 1.15.

```latex
\linespread{1.15}
```

---

## 5. Section titles (centered) and subsection titles (left-aligned)

Word `Heading1`: `<w:jc w:val="center"/>`, `<w:sz w:val="28"/>`, `<w:color w:val="005FAF"/>`.

```latex
\usepackage{titlesec}

% Word Heading1 : sz=28 half-pts = 14pt, jc=center, color=005FAF
\titleformat{\section}
  {\color{mitacsblue}\fontsize{14}{17}\selectfont\bfseries\filcenter}
  {}{0em}{}
\titlespacing*{\section}{0pt}{14pt plus 2pt minus 2pt}{6pt plus 1pt minus 1pt}

% Word Heading2 : sz=28 half-pts = 14pt, gauche
\titleformat{\subsection}
  {\fontsize{14}{17}\selectfont\bfseries\raggedright}
  {}{0em}{}
\titlespacing*{\subsection}{0pt}{14pt plus 2pt minus 2pt}{6pt plus 1pt minus 1pt}
```

Color definition (before `geometry`):

```latex
\usepackage[table]{xcolor}
\definecolor{mitacsblue}{HTML}{005FAF}
\definecolor{mitacsdarkblue}{HTML}{002F57}
```

---

## 6. Tables with full grid

Word `<w:tblBorders>` with `insideH` and `insideV` non-`nil` → every column
needs `|`, every row needs a trailing `\hline`.

### 6a. Column spec — add `|` between columns

Before:
```latex
\begin{longtable}[]{@{}
  >{\raggedright\arraybackslash}p{(\linewidth - 6\tabcolsep) * \real{0.3334}}
  >{\raggedright\arraybackslash}p{(\linewidth - 6\tabcolsep) * \real{0.2561}}
  ...
  >{\raggedright\arraybackslash}p{(\linewidth - 6\tabcolsep) * \real{0.1897}}@{}}
```

After:
```latex
\begin{longtable}[]{@{}|
  >{\raggedright\arraybackslash}p{(\linewidth - 8\tabcolsep) * \real{0.3334}}|
  >{\raggedright\arraybackslash}p{(\linewidth - 8\tabcolsep) * \real{0.2561}}|
  ...
  >{\raggedright\arraybackslash}p{(\linewidth - 8\tabcolsep) * \real{0.1897}}|@{}}
```

The trailing `|@{}}` order matters — `@{}}|` is wrong (the `|` would be outside
the column spec brace).

### 6b. Replace booktabs rules with `\hline`

```
\toprule\noalign{}     →  \hline
\midrule\noalign{}     →  \hline
\bottomrule\noalign{}  →  \hline
```

Also add `\hline` after every data row inside the body of the longtable. The
`\endhead` / `\endlastfoot` boundaries are unchanged.

---

## 7. First-page banner (TikZ overlay)

Identify the white-logo PNG by running the inspector — it has RGB ≈ (255,255,255)
with varying alpha. Typically `image4.png` or `image6.png` in Mitacs templates.

```latex
\usepackage{tikz}

% On the first page only:
\thispagestyle{plain}
\begin{tikzpicture}[remember picture, overlay]
  % Bandeau bleu 3,5 cm de haut, pleine largeur
  \fill[mitacsblue]
    (current page.north west) rectangle ([yshift=-3.5cm]current page.north east);
  % Logo blanc à gauche
  \node[anchor=west, inner sep=0pt, xshift=1.2cm, yshift=-1.5cm]
    at (current page.north west)
    {\includegraphics[height=1.4cm]{image4.png}};
  % Titre centré en blanc
  \node[anchor=center, text=white, font=\fontsize{14}{19}\selectfont\bfseries]
    at ([yshift=-2.5cm]current page.north)
    {Proposition de recherche Accélération};
  % Pictogramme circulaire à droite
  \node[anchor=east, inner sep=0pt, xshift=-1.2cm, yshift=-1.75cm]
    at (current page.north east)
    {\includegraphics[height=1.8cm]{image3.png}};
\end{tikzpicture}
\vspace*{1.2cm}
```

---

## 8. Header and footer (`fancyhdr`)

```latex
\usepackage{fancyhdr}
\usepackage{lastpage}

% Le logo image1.png est un bandeau ~7.5:1 ; on contraint la largeur
% pour laisser place au titre à droite (sinon le texte sort de la page).
\pagestyle{fancy}
\fancyhf{}
\fancyhead[L]{\includegraphics[height=0.8cm,width=3.5cm,keepaspectratio]{image1.png}}
\fancyhead[R]{\color{mitacsblue}\bfseries\small <title>}
\fancyfoot[L]{\footnotesize <left-footer-from-word>}
\fancyfoot[R]{\footnotesize \thepage\ de \pageref*{LastPage}}
% \headrulewidth=0pt évite le filet sous l'en-tête et l'espace blanc
% visible entre le logo et le filet.
\renewcommand{\headrulewidth}{0pt}
\renewcommand{\footrulewidth}{0pt}

% Première page : pas d'en-tête, pied seul
\fancypagestyle{plain}{%
  \fancyhf{}%
  \fancyfoot[L]{\footnotesize <left-footer-from-word>}%
  \fancyfoot[R]{\footnotesize \thepage\ de \pageref*{LastPage}}%
  \renewcommand{\headrulewidth}{0pt}%
  \renewcommand{\footrulewidth}{0pt}%
}
```

---

## 9. Landscape sections (Legal-landscape 14×8.5 in)

Use only if `<w:pgSz w:w="20160" w:h="12240" w:orient="landscape"/>` is in the
docx. **Do not** put `paperwidth`/`paperheight`/`landscape` inside
`\newgeometry` — the geometry package skips them and prints a warning.

```latex
% === Bascule en format légal paysage (14 x 8,5 po) ===
% Note : geometry n'autorise pas paperwidth/paperheight dans \newgeometry ;
% on les pose via \pdfpagewidth/\pdfpageheight + \paperwidth/\paperheight,
% puis on ajuste la zone de texte avec layoutwidth/layoutheight.
\newcommand{\OpenLegalLand}{%
  \clearpage
  \pdfpagewidth=14in\pdfpageheight=8.5in
  \paperwidth=14in\paperheight=8.5in
  \newgeometry{%
    layoutwidth=14in,layoutheight=8.5in,%
    hmargin=2.54cm,vmargin=2.54cm,%
    headheight=1.5cm,headsep=0.4cm,footskip=0.8cm}%
}
\newcommand{\CloseLegalLand}{%
  \clearpage
  \restoregeometry
  \pdfpagewidth=8.5in\pdfpageheight=11in
}
```

**Naming:** never use `\beginX` / `\endX` for these macros — LaTeX's
`\begin{X}` / `\end{X}` machinery reserves those names and you will get
"Command \endX already defined".

**Usage pattern — text and table together:**

```latex
\OpenLegalLand

\noindent\textbf{\large Calendrier des projets ...}

\begin{enumerate}
\setlength{\itemsep}{0pt}
\setlength{\parskip}{0pt}
\item ...
\end{enumerate}

\vspace{4pt}
\footnotesize
\setlength{\tabcolsep}{1.5pt}
\renewcommand{\arraystretch}{0.95}
\begin{longtable}[]{...}
...
\end{longtable}

\vspace{2pt}
{\footnotesize\emph{\(\nwarrow\) ... caption ...}}

\CloseLegalLand
```

---

## 10. Compact calendar table cells

If a row in the calendar table contains:

```latex
\begin{minipage}[t]{\linewidth}\raggedleft
\begin{enumerate}
\def\labelenumi{\arabic{enumi})}
\item
  \textbf{Écrivez le sous-objectif ici.}
\end{enumerate}
\end{minipage}
```

Replace it with plain text — the minipage + enumerate combination triples the
row height for no semantic benefit:

```latex
\textbf{1) Écrivez le sous-objectif ici.}
```

Update each sub-objectif row to use its index (`1)`, `2)`, `3)`, `4)`)
explicitly, removing the per-row `\setcounter{enumi}{N}` and minipage wrapper.

---

## 11. Author and date suppression

Word templates rarely use `\author{}` or `\date{}`. Pandoc emits them anyway.

```latex
\author{}
\date{}
```

Place before `\begin{document}`.

---

## Quick cross-reference: Word value → LaTeX

| Word XML | LaTeX |
|---|---|
| `<w:sz w:val="22"/>` (default) | `\documentclass[11pt]{article}` |
| `<w:sz w:val="28"/>` (Heading1) | `\fontsize{14}{17}\selectfont` |
| `<w:sz w:val="18"/>` (footer) | `\footnotesize` (≈ 9 pt at 11 pt base) |
| `<w:spacing w:line="276"/>` | `\linespread{1.15}` |
| `<w:spacing w:line="240"/>` | single spacing (no `\linespread`) |
| `<w:jc w:val="center"/>` | `\filcenter` (titlesec) or `\centering` |
| `<w:jc w:val="right"/>` | `\raggedleft` |
| `<w:pgMar w:top="993"/>` | `top=1.75cm` (993 twips = 0.69 in) |
| `<w:pgMar w:top="1440"/>` | `top=2.54cm` (1440 twips = 1 in) |
| `<w:pgSz w:orient="landscape" w:w="20160" w:h="12240"/>` | Legal-landscape 14×8.5 in |
| `<w:pgSz w:orient="landscape" w:w="15840" w:h="12240"/>` | Letter-landscape 11×8.5 in |
| `<w:tblBorders><w:insideH .../><w:insideV .../></w:tblBorders>` | `|` between columns + `\hline` after each row |
| `<w:color w:val="005FAF"/>` | `\definecolor{x}{HTML}{005FAF}` |
| `<w:titlePg/>` | `\thispagestyle{plain}` on first page |

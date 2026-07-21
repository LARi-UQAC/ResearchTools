"""
letter_templates.py - all embedded string constants and lookup maps for the
recommendation-letter skill. No logic here; generate_letter.py imports these.
Kept separate so the assembly logic stays small and testable.

LaTeX output uses UTF-8 accented characters directly (the preamble loads
inputenc utf8), not backslash-accent macros. Straight quotes only; no em dash,
no invisible characters (repo style-hygiene rules, AI-usage < 20%).
"""

# --- Shared scaffold ------------------------------------------------------

PREAMBLE = r"""\documentclass[11pt, letterpaper]{article}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{lmodern}
\usepackage[%%BABEL_LANGUAGE%%]{babel}
\usepackage[top=2.0cm, bottom=2.0cm, left=2.54cm, right=2.54cm]{geometry}
\usepackage{graphicx}
\usepackage{xcolor}
\usepackage[hidelinks]{hyperref}
\usepackage{parskip}
\setlength{\parskip}{6pt}
\setlength{\parindent}{0pt}
\usepackage{fancyhdr}
\pagestyle{fancy}
\fancyhf{}
\renewcommand{\headrulewidth}{0pt}
\renewcommand{\footrulewidth}{0pt}
"""

LETTERHEAD_FR = r"""\begin{document}
\noindent
\IfFileExists{uqac_logo.png}{\includegraphics[width=5cm]{uqac_logo.png}\hfill}{}%
\begin{minipage}[t]{0.55\textwidth}
\raggedleft\small
Professeur Martin Otis\\
Département des sciences appliquées\\
Université du Québec à Chicoutimi (UQAC)\\
555, boul.\ de l'Université, Chicoutimi (QC)\\
Canada, G7H 2B1
\end{minipage}
\vspace{12pt}\hrule\vspace{12pt}
"""

LETTERHEAD_EN = r"""\begin{document}
\noindent
\IfFileExists{uqac_logo.png}{\includegraphics[width=5cm]{uqac_logo.png}\hfill}{}%
\begin{minipage}[t]{0.55\textwidth}
\raggedleft\small
Professor Martin Otis\\
Department of Applied Sciences\\
Université du Québec à Chicoutimi (UQAC)\\
555, boul.\ de l'Université, Chicoutimi (QC)\\
Canada, G7H 2B1
\end{minipage}
\vspace{12pt}\hrule\vspace{12pt}
"""

SIGNATURE_FR = r"""\vspace{18pt}
Cordialement,

\vspace{24pt}
\textbf{Martin J.-D. Otis, ing. M.Sc.A. Ph.D.}\\
{\small Professeur titulaire en génie électrique et informatique de l'UQAC}\\
{\small Membre RISUQ, Centre CISD \& Regroupement ReSMIQ}\\
{\small Responsable du Laboratoire d'Automatique et de Robotique interactive (LAR.i)}\\
{\small Tél.~: (418) 545-5011 (poste 2577)}\\
{\small Courriel~: \href{mailto:Martin_Otis@uqac.ca}{Martin\_Otis@uqac.ca}}\\
{\small Site Web~: \href{https://lari.uqac.ca}{lari.uqac.ca}}
\end{document}
"""

SIGNATURE_EN = r"""\vspace{18pt}
Best regards,

\vspace{24pt}
\textbf{Martin J.-D. Otis, P.Eng., M.Sc.A., Ph.D.}\\
{\small Full Professor in Electrical and Computer Engineering, UQAC}\\
{\small Member RISUQ, CISD Centre \& ReSMIQ Group}\\
{\small Director, Interactive Automation and Robotics Laboratory (LAR.i)}\\
{\small Tel.: (418) 545-5011 (ext.\ 2577)}\\
{\small Email: \href{mailto:Martin_Otis@uqac.ca}{Martin\_Otis@uqac.ca}}\\
{\small Web: \href{https://lari.uqac.ca}{lari.uqac.ca}}
\end{document}
"""

# --- Gender placeholders (French form templates) --------------------------
# {placeholder_without_percents: (male, female)}. Applied last, after all
# other placeholders, as plain string replacement.
GENDER_MAP = {
    "GENDER_E": ("", "e"),
    "GENDER_CELUI": ("celui-ci", "celle-ci"),
    "GENDER_HEUREUX": ("heureux", "heureuse"),
    "GENDER_IL": ("Il", "Elle"),
    "GENDER_DE_ETUDIANT": ("de l'étudiant", "de l'étudiante"),
    "SALUTATION": ("Monsieur,", "Madame,"),
}

# --- Acceptance letter (French only) --------------------------------------

DEGREE_DESCRIPTION = {
    "msc": "une maîtrise de recherche (deuxième cycle)",
    "phd": "une thèse de doctorat (troisième cycle, profil recherche)",
    "phd_eng": "une thèse (doctorat en ingénierie, troisième cycle)",
    "research_stay": "un séjour de recherche",
}

TEMPLATE_ACCEPTANCE_FR = r"""%%LETTERHEAD_FR%%

%%DATE%%

\textbf{Objet~: Confirmation d'acceptation de %%CANDIDATE_NAME%% au sein du Laboratoire LAR.i de l'Université du Québec à Chicoutimi (UQAC).}

\vspace{6pt}

%%SALUTATION%%

En tant que futur directeur de recherche de l'étudiant%%GENDER_E%%, je confirme que %%GENDER_CELUI%% a été accepté%%GENDER_E%% pour réaliser %%DEGREE_DESCRIPTION%% au sein du laboratoire LAR.i de l'Université du Québec à Chicoutimi (UQAC). L'équipe du LAR.i est très %%GENDER_HEUREUX%% de recevoir %%CANDIDATE_NAME%%. Son projet de recherche porte sur %%PROJECT_DESCRIPTION%%. %%LAB_COLLABORATORS_SENTENCE%% %%MITACS_OPPORTUNITY_SENTENCE%%

%%PROJECT_DETAILS_PARAGRAPH%%

%%FUNDING_PARAGRAPH%%

%%PREREQUISITES_PARAGRAPH%%

Nous restons disponibles pour toutes questions concernant la situation %%GENDER_DE_ETUDIANT%% sous notre supervision.

Veuillez agréer l'expression de nos sentiments les meilleurs.

%%SIGNATURE_FR%%
"""

# --- Dispense letter (French only, standalone document) -------------------

IMMIGRATION_PARAGRAPH_STANDARD = (
    "Vous êtes responsable de vérifier sur le site Web d'Immigration Canada "
    "quelles exigences d'autorisation d'entrée au Canada s'appliquent à votre "
    "situation et de tenir compte des délais à prévoir pour le traitement des "
    "demandes au Canada et dans les bureaux canadiens des visas à l'étranger. "
    "En vertu de la dispense de permis de travail visant les périodes de "
    "recherche en milieu universitaire de courte durée (120 jours ou moins) en "
    "vigueur depuis juin 2017, vous pourriez être autorisé à travailler au "
    "Canada sans permis de travail. Veuillez consulter le site d'Immigration "
    "Canada pour déterminer votre admissibilité")

IMMIGRATION_EXTRA_CLAUSE = (
    ", autrement, une validation auprès de l'immigration est requise de votre part")

CONDITIONAL_SENTENCE = (
    "Cette lettre est conditionnelle à l'obtention de la bourse "
    "%%CONDITIONAL_SCHOLARSHIP_NAME%%. ")

TEMPLATE_DISPENSE_FR = r"""\documentclass[11pt, letterpaper]{article}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{lmodern}
\usepackage[french]{babel}
\usepackage[top=2.0cm, bottom=2.0cm, left=2.54cm, right=2.54cm]{geometry}
\usepackage[hidelinks]{hyperref}
\usepackage{parskip}
\setlength{\parindent}{0pt}
\begin{document}

\noindent Chicoutimi, %%DATE%%

\vspace{12pt}

\noindent %%CANDIDATE_NAME_UPPER%%\\
%%CANDIDATE_ADDRESS%%

\vspace{12pt}

\noindent\textbf{Objet~: SÉJOUR DE RECHERCHE en tant que chercheur%%GENDER_E%% invité%%GENDER_E%% à l'Université du Québec à Chicoutimi pour MOINS DE 120 JOURS}

\vspace{12pt}

\noindent %%SALUTATION%%

\vspace{6pt}

J'ai le plaisir de vous inviter à effectuer un séjour de recherche à l'Université du Québec à Chicoutimi sous ma direction considérant que vous jouez un rôle important dans le projet de recherche et que vous possédez une expertise dans un domaine lié aux travaux de recherche visés.

\vspace{6pt}

\begin{tabular}{@{}p{5.5cm}p{9.5cm}@{}}
\textbf{Lieu de séjour~:} & Université du Québec à Chicoutimi\\
  & 555, boul.\ de l'Université\\
  & Chicoutimi, Québec, Canada\\[6pt]
\textbf{Responsable~:} & Martin Otis\\[6pt]
\textbf{Dates~:} & Du %%STAY_START%% au %%STAY_END%% inclusivement.\\[6pt]
\textbf{Rémunération~:} & %%REMUNERATION%%\\[6pt]
\textbf{Nombre d'heures hebdomadaires~:} & %%WEEKLY_HOURS%%\\[6pt]
\textbf{Nom de l'établissement d'origine~:} & %%HOME_INSTITUTION%%\\[6pt]
\textbf{Titre du poste~:} & Chercheur%%GENDER_E%% invité%%GENDER_E%%\\[6pt]
\textbf{Tâches~:} & %%TASKS_DESCRIPTION%%\\
\end{tabular}

\vspace{12pt}

%%CONDITIONAL_PARAGRAPH%%%%IMMIGRATION_PARAGRAPH%%.

\vspace{6pt}

N'hésitez pas à communiquer avec moi si vous avez besoin de renseignements complémentaires.

\vspace{12pt}

Sincères salutations,

\vspace{24pt}

\noindent\textbf{Martin J.-D. Otis, ing. M.Sc.A. Ph.D.}\\
{\small Professeur titulaire -- Université du Québec à Chicoutimi}\\
{\small \href{https://lari.uqac.ca}{lari.uqac.ca}}

\end{document}
"""
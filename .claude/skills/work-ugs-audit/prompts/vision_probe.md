Look at the figure in the image. It can be any kind of figure of a technical or project report: a chart, a Gantt
chart, a diagram, a flowchart, a technical drawing, a photo or something else.

Return one JSON object with these keys and nothing else:

- figure_kind: the kind of the figure, one of chart, gantt, diagram, flowchart, technical_drawing, table, photo, other.
  chart: values drawn on axes, including a bar chart, a pie chart, a budget chart and an S-curve (a cumulative
  curve of cost or progress against time). gantt: tasks drawn as bars on a time scale. diagram: boxes linked by
  lines or arrows, including UML (use case, class, sequence, state), SysML, a software or electronic architecture,
  a block diagram, a project or product breakdown structure (PBS, WBS) and an organisation chart. flowchart: steps
  and decisions in sequence, including a logigram and an activity diagram. technical_drawing: a CAD view, a PCB
  layout, an electrical schematic or a mechanical drawing. table: a grid of rows and columns, such as a budget or a
  timesheet, even when its printed title says Figure. photo: a photograph. other: anything else, including a Kanban
  board and a screenshot.
- visible_text: the list of the words and short phrases printed on the figure (titles, labels, legend entries,
  task names, column headings, part names), each copied exactly as written. Use an empty list when nothing is
  printed.

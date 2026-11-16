Look at the figure in the image. It can be any kind: a chart, a Gantt chart, a diagram, a flowchart, a technical
drawing (a CAD view, a PCB layout, an electrical or mechanical drawing), a photo or something else.

Return one JSON object with these keys and nothing else:

- figure_kind: the kind of the figure, one of chart, gantt, diagram, flowchart, technical_drawing, photo, other.
- visible_text: the list of the words and short phrases printed on the figure (titles, labels, legend entries,
  task names, part names), each copied exactly as written. Use an empty list when nothing is printed.

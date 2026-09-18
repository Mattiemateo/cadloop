# Dependencies and primary references

The ZIP contains CADLoop source and generated fixture artifacts, not vendored third-
party library code, wheels or font files. Dependencies retain their respective
licenses. CadQuery's dependency stack includes additional native libraries; this
file is not a completed license audit.

Primary documentation used while implementing the interfaces:

- https://build123d.readthedocs.io/en/latest/import_export.html
- https://pypi.org/pypi/build123d/json
- https://cadquery.readthedocs.io/en/latest/classreference.html
- https://dev.opencascade.org/doc/refman/html/class_b_rep_extrema___dist_shape_shape.html
- https://dev.opencascade.org/doc/refman/html/class_b_rep_algo_a_p_i___common.html
- https://docs.docker.com/engine/containers/run/
- https://developers.openai.com/api/reference/resources/chat

Original planned upstream executor (not integrated in this prototype):
https://github.com/jdilla1277/agentcad

Documentation inspection is not a claim of live-provider compatibility or successful
Docker execution. Actual tested packages and versions are in evidence/environment.json.

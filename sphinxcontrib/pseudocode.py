# -*- coding: utf-8 -*-
"""
    sphinx-pseudocode
    ~~~~~~~~~~~~~~~~~

    Allow typeset algorithms in latex powered by pseudocode.js inside sphinx-doc

    :copyright: Copyright 2021 by Zeyuan Hu.
    :license: BSD, see LICENSE for details.
"""

import os
import re
import shutil
from tempfile import mkdtemp
from textwrap import dedent

import jinja2
import sphinx
from docutils import nodes
from docutils.parsers.rst import Directive, directives
from docutils.statemachine import ViewList
from sphinx.domains.std import StandardDomain
from sphinx.util import logging

logger = logging.getLogger(__name__)

mapname_re = re.compile(r'<map id="(.*?)"')

filename_autorenderer = 'katex_autorenderer_{}.js'

PROOF_HTML_TITLE_TEMPLATE_VISIT = """ 
    pseudocode.renderElement(
    document.getElementById("{{ id }}"), {
        {% if captionCount %} captionCount: {{ captionCount }} ,{% endif %}
        {% if lineNumber %} lineNumber: true {% endif %}
    });\n
"""


class pseudocode(nodes.General, nodes.Element):
    pass


class pseudocodeContentNode(nodes.General, nodes.Element):
    """Content of pseudocode."""
    pass

class pseudocodeCaption(nodes.caption):
    """Caption of pseudocode."""
    pass

class Pseudocode(Directive):
    """An environment for pseudocode."""
    has_content = True
    required_arguments = 0
    optional_arguments = 0
    final_argument_whitespace = False
    option_spec = {
        'linenos': directives.unchanged
    }

    def get_mm_code(self):
        pcode = '\n'.join(self.content)
        if not pcode.strip():
            return [self.state_machine.reporter.warning(
                'Ignoring "pcode" directive without content.',
                line=self.lineno)]
        return pcode

    def run(self):
        node = pseudocode()
        node['code'] = self.get_mm_code()
        node = pseudocode_wrapper(self, node)

        content = pseudocodeContentNode()
        content['code'] = self.get_mm_code()
        content['options'] = {}
        if 'linenos' in self.options:
            content['linenos'] = True

        node += content

        self.add_name(node)
        return [node]


def render_mm_html(self, node, code, options, prefix='pseudocode',
                   imgcls=None, alt=None):
    tag_template = """<pre id="{id}" style="display:none;">
            {code}
        </pre>"""
    figure_id = get_fignumber(self, node)
    if not figure_id:
        # Generate a unique ID if get_fignumber returns empty
        figure_id = f"pseudocode-{id(node)}"
    self.body.append(tag_template.format(id=figure_id, code=self.encode(code)))
    node['id'] = figure_id


def write_katex_autorenderer_file(app, filename, dicts):
    # Write to the actual static output path instead of temp directory
    static_path = os.path.join(app.builder.outdir, '_static')
    os.makedirs(static_path, exist_ok=True)
    filename = os.path.join(static_path, filename)
    content = katex_autorenderer_content(app, dicts)
    with open(filename, 'w') as file:
        file.write(content)


def katex_autorenderer_content(app, dicts):
    content = dedent('''\
            document.addEventListener("DOMContentLoaded", function() {{
              {functions}
            }});''')
    functions = ''
    for i, pairs in enumerate(dicts):
        if (pairs['id'] != ''):
            # Use the index as caption count, but start from 0 to match pseudocode.js numbering
            # pseudocode.js will increment this to get Algorithm 1, Algorithm 2, etc.
            captionCount = i
            functions += jinja2.Template(PROOF_HTML_TITLE_TEMPLATE_VISIT).render(
                id=pairs['id'],
                captionCount=captionCount,
                lineNumber=pairs['linenos']
            )

    content = content.format(functions=functions)
    prefix = ''
    suffix = ''
    options = ''
    delimiters = ''
    return '\n'.join([prefix, options, delimiters, suffix, content])


def config_inited(app, config):
    """Add algorithm packages for LaTeX output and set default numfig format."""
    # Set default numfig format for pcode if not specified
    if hasattr(config, 'numfig_format'):
        if config.numfig_format is None:
            config.numfig_format = {}
        config.numfig_format.setdefault('pcode', '%s')
    
    # Add algorithm packages for LaTeX output
    if hasattr(config, 'latex_elements'):
        if config.latex_elements is None:
            config.latex_elements = {}
        preamble = config.latex_elements.get('preamble', '')
        algorithm_packages = r'''
\usepackage{algorithm}
\usepackage{algorithmic}
% Add missing commands for compatibility
\newcommand{\PROCEDURE}[2]{\STATE \textbf{procedure } \textsc{#1}(#2)}
\newcommand{\ENDPROCEDURE}{\STATE \textbf{end procedure}}
\newcommand{\CALL}[2]{\textsc{#1}(#2)}
% Configure algorithm counter to reset per chapter and use hierarchical numbering
\makeatletter
\@addtoreset{algorithm}{chapter}
\renewcommand{\thealgorithm}{\thechapter.\arabic{algorithm}}
\makeatother
'''
        if algorithm_packages not in preamble:
            config.latex_elements['preamble'] = preamble + algorithm_packages


def builder_inited(app):
    setup_static_path(app)
    install_js(app)


def install_js(app, *args):
    # add required javascript
    app.add_js_file(f"https://cdn.jsdelivr.net/npm/pseudocode@latest/build/pseudocode.js")
    old_css_add = getattr(app, 'add_stylesheet', None)
    add_css = getattr(app, 'add_css_file', old_css_add)
    add_css(f"https://cdn.jsdelivr.net/npm/pseudocode@latest/build/pseudocode.min.css")
    app.add_js_file(f"https://cdnjs.cloudflare.com/ajax/libs/KaTeX/0.11.1/katex.min.js")


def install_js2_part2(app, pagename, templatename, context, doctree):
    """
    Generate katex_autorenderer.js based on ids of each pcode and associated options so that
    we can create associate document.getElementById functions. Then, we register katex_autorenderer.js.
    """
    dicts = []
    if doctree is not None:
        for node in doctree.traverse(pseudocodeContentNode):
            node_id = node.get('id', '')
            if not node_id:
                # Generate a unique ID if not already set
                node_id = f"pseudocode-{id(node)}"
                node['id'] = node_id
            pairs = {'id': node_id,
                     'linenos': True if 'linenos' in node else False,
                     'parentId': node.parent.attributes.get('ids')[0] if node.parent.attributes.get('ids') else ''}
            dicts.append(pairs)
        if len(dicts) > 0:
            filename_autorenderer_specific = filename_autorenderer.format(
                os.path.split(doctree.attributes.get('source'))[-1].split('.')[0])
            write_katex_autorenderer_file(app, filename_autorenderer_specific, dicts)
            app.add_js_file(filename_autorenderer_specific)


def setup_static_path(app):
    app._katex_static_path = mkdtemp()
    if app._katex_static_path not in app.config.html_static_path:
        app.config.html_static_path.append(app._katex_static_path)


def builder_finished(app, exception):
    # Delete temporary dir used for _static file
    shutil.rmtree(app._katex_static_path)


def pseudocode_wrapper(directive, node, caption=None):
    """Parse caption, and append it to the node."""
    parsed = nodes.Element()
    if caption is None:
        caption_node = pseudocodeCaption()
    else:
        directive.state.nested_parse(
            ViewList([caption], source=""), directive.content_offset, parsed
        )
        caption_node = pseudocodeCaption(parsed[0].rawsource, "", *parsed[0].children)
        caption_node.source = parsed[0].source
        caption_node.line = parsed[0].line
    node += caption_node
    return node


class PseudocodeDomain(StandardDomain):
    """Pseudocode domain"""

    name = "pseudocodecounter"
    label = "Pseudocode Counter"

    directives = {"pseudocode": Pseudocode}


def get_pseudocode_title(node):
    """Title getter function for pseudocode nodes."""
    # Look for a caption first
    for child in node.children:
        if isinstance(child, pseudocodeCaption):
            caption_text = child.astext().strip()
            if caption_text:
                return caption_text
    
    # Look for algorithm caption in the content
    for child in node.children:
        if isinstance(child, pseudocodeContentNode):
            code = child.get('code', '')
            # Extract caption from \caption{...} 
            import re
            caption_match = re.search(r'\\caption\{([^}]+)\}', code)
            if caption_match:
                return caption_match.group(1)
    
    return "Algorithm"


################################################################################
# HTML
def get_fignumber(writer, node):
    """Compute and return the theorem number of `node`."""
    # Copied from the sphinx project: sphinx.writers.html.HTMLTranslator.add_fignumber()
    if isinstance(node, pseudocodeContentNode) and isinstance(node.parent, pseudocode):
        parent = node.parent
        if parent.get("ids"):
            figure_id = parent["ids"][0]
            key = "pcode"
            if hasattr(writer.builder, 'fignumbers') and key in writer.builder.fignumbers:
                if figure_id in writer.builder.fignumbers[key]:
                    return ".".join(map(str, writer.builder.fignumbers[key][figure_id]))
    return ""


def html_visit_stuff_node(self, node):
    """Enter :class:`pseudocode` in HTML builder."""
    self.body.append(self.starttag(node, "div", CLASS="pseudocode"))
    # Add figure number to pseudocode
    self.add_fignumber(node)


def html_depart_stuff_node(self, node):
    """Leave :class:`pseudocode` in HTML builder."""
    self.body.append("</div>")


def html_visit_caption_node(self, node):
    """Enter :class:`CaptionNode` in HTML builder."""
    self.body.append(self.starttag(node, "div", CLASS="pseudocode-caption"))
    if node.astext():
        self.body.append(" — ")
        self.body.append(self.starttag(node, "span", CLASS="caption-text"))


def html_depart_caption_node(self, node):
    """Leave :class:`CaptionNode` in HTML builder."""
    if node.astext():
        self.body.append("</span>")
    self.body.append("</div>")


def html_visit_pseudocode_content_node(self, node):
    """Enter :class:`pseudocodeContentNode` in HTML builder."""
    self.body.append(self.starttag(node, "div", CLASS="pseudocode-content"))
    render_mm_html(self, node, node['code'], node['options'])


def html_depart_pseudocode_content_node(self, node):
    """Leave :class:`pseudocodeContentNode` in HTML builder."""
    self.body.append("</div>")


################################################################################
# LaTeX
def latex_visit_stuff_node(self, node):
    """Enter :class:`pseudocode` in LaTeX builder."""
    # Add figure number to pseudocode for LaTeX
    if hasattr(self, 'add_fignumber'):
        self.add_fignumber(node)


def latex_depart_stuff_node(self, node):
    """Leave :class:`pseudocode` in LaTeX builder."""
    pass


def latex_visit_caption_node(self, node):
    """Enter :class:`CaptionNode` in LaTeX builder."""
    pass


def latex_depart_caption_node(self, node):
    """Leave :class:`CaptionNode` in LaTeX builder."""
    pass


def latex_visit_pseudocode_content_node(self, node):
    """Enter :class:`pseudocodeContentNode` in LaTeX builder."""
    # For LaTeX, we output the raw LaTeX code and add labels for cross-referencing
    self.body.append('\n')
    
    # Get the pseudocode node (parent) to access its IDs
    parent_node = node.parent
    code = node['code']
    
    # Add labels after the \caption command for proper algorithm numbering
    if parent_node and parent_node.get("ids"):
        # Find the \caption command and add labels after it
        import re
        caption_pattern = r'(\\caption\{[^}]+\})'
        
        def add_labels_after_caption(match):
            caption = match.group(1)
            labels = []
            for node_id in parent_node["ids"]:
                # Get document name for proper label format
                if hasattr(parent_node, 'document') and hasattr(parent_node.document, 'attributes'):
                    source_path = parent_node.document.attributes.get('source', '')
                    # Convert Windows backslashes to forward slashes for LaTeX compatibility
                    source_path = source_path.replace('\\', '/')
                    docname = source_path.split('/')[-1].split('.')[0]
                    if docname:
                        full_label = f"{docname}:{node_id}"
                    else:
                        full_label = node_id
                else:
                    full_label = node_id
                labels.append(f'\\label{{{full_label}}}')
            return caption + '\n' + '\n'.join(labels)
        
        # Replace the caption with caption + labels
        code = re.sub(caption_pattern, add_labels_after_caption, code)
    
    self.body.append(code)
    self.body.append('\n')


def latex_depart_pseudocode_content_node(self, node):
    """Leave :class:`pseudocodeContentNode` in LaTeX builder."""
    pass


def setup(app):
    """Setup extension.
    """
    app.add_domain(PseudocodeDomain)

    app.add_enumerable_node(
        pseudocode,
        "pcode",
        title_getter=get_pseudocode_title,
        html=(html_visit_stuff_node, html_depart_stuff_node),
        latex=(latex_visit_stuff_node, latex_depart_stuff_node),
    )
    app.add_node(
        pseudocodeCaption,
        html=(html_visit_caption_node, html_depart_caption_node),
        latex=(latex_visit_caption_node, latex_depart_caption_node),
    )
    app.add_node(
        pseudocodeContentNode,
        html=(html_visit_pseudocode_content_node, html_depart_pseudocode_content_node),
        latex=(latex_visit_pseudocode_content_node, latex_depart_pseudocode_content_node),
    )

    app.add_directive('pcode', Pseudocode)
    # Allow users to customize format via numfig_format in conf.py
    # Default will be handled by Sphinx if not specified
    app.connect('config-inited', config_inited)
    app.connect('builder-inited', builder_inited)
    app.connect('html-page-context', install_js2_part2)
    app.connect('build-finished', builder_finished)

    return {'version': sphinx.__display_version__, 'parallel_read_safe': True}

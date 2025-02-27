# Copyright 2015 Google Inc. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Escaping functions for compiled soy templates.

This module contains the public functions and classes to sanitize content for
different contexts.

The bulk of the logic resides in generated_sanitize.py which is generated by
GeneratePySanitizeEscapingDirectiveCode.java to match other implementations.
Please keep as much escaping and filtering logic/regex in there as possible.

Most of the functions in this file mirror the functions in
com.google.template.soy.shared.internal.Sanitizers where are their comments.
"""

# Emulate Python 3 style unicode string literals.
from __future__ import unicode_literals

__author__ = 'dcphillips@google.com (David Phillips)'

import functools
import html as html_module
import re

from . import generated_sanitize

import six

# To allow the rest of the file to assume Python 3 strings, we will assign str
# to unicode for Python 2. This will error in 3 and be ignored.
try:
  str = unicode
except NameError:
  pass


#############
# Constants #
#############


# Matches html attribute endings which are ambiguous (not ending with space or
# quotes).
_AMBIGUOUS_ATTR_END_RE = re.compile(r'([^"\'\s])$')


# Matches any/only HTML5 void elements' start tags.
# See http://www.w3.org/TR/html-markup/syntax.html#syntax-elements
_HTML5_VOID_ELEMENTS_RE = re.compile(
    '^<(?:area|base|br|col|command|embed|hr|img|input'
    '|keygen|link|meta|param|source|track|wbr)\\b')


# An innocuous output to replace filtered content with.
# For details on its usage, see the description in
_INNOCUOUS_OUTPUT = 'zSoyz'


# Regex for various newline combinations.
_NEWLINE_RE = re.compile('(\r\n|\r|\n)')


# Regex for finding replacement tags.
_REPLACEMENT_TAG_RE = re.compile(r'\[(\d+)\]')

# Regex for finding patterns that could start a token which ends a
# raw content block.
_HTML_RAW_CONTENT_HAZARD_RE = re.compile(r'<\/|\]\]>')

# Replacement strings for matches of _HTML_RAW_CONTENT_HAZARD_RE
# that are semantically equivalent in CSS stylesheets.
# See Sanitizers.java for a more detailed analysis.
_HTML_RAW_CONTENT_HAZARD_REPLACEMENTS = {'</': r'<\/', ']]>': r']]\>'}


#######################################
# Soy public directives and functions #
#######################################


def change_newline_to_br(value):
  html = _get_content_of_kind(value, CONTENT_KIND.HTML)

  if html is not None:
    result = _NEWLINE_RE.sub('<br>', html)
    approval = IActuallyUnderstandSoyTypeSafetyAndHaveSecurityApproval(
        'Persisting existing sanitization.')
    return SanitizedHtml(result, get_content_dir(value), approval=approval)

  return _NEWLINE_RE.sub('<br>', str(value))


def clean_html(value, safe_tags=None):
  if not safe_tags:
    safe_tags = generated_sanitize._SAFE_TAG_WHITELIST
  else:
    # Join the provided list with the default whitelist.
    safe_tags = list(
        set(safe_tags).union(generated_sanitize._SAFE_TAG_WHITELIST))

  html = _get_content_of_kind(value, CONTENT_KIND.HTML)
  if html is not None:
    approval = IActuallyUnderstandSoyTypeSafetyAndHaveSecurityApproval(
        'Persisting existing sanitization.')
    return SanitizedHtml(html, get_content_dir(value), approval=approval)

  approval = IActuallyUnderstandSoyTypeSafetyAndHaveSecurityApproval(
      'Escaped html is by nature sanitized.')
  return SanitizedHtml(_strip_html_tags(value, safe_tags),
                       get_content_dir(value), approval=approval)

# LINT.IfChange(htmlToText)
_TAG_RE = re.compile(
    r'<(?:!--.*?--|(?:!|(/?[a-z][\w:-]*))((?:[^>\'"]|"[^"]*"|\'[^\']*\')*))>|\Z',
    re.IGNORECASE)
_ATTR_RE = re.compile(
    r'([a-zA-Z][a-zA-Z0-9:\\-]*)[\t\n\r ]*=[\t\n\r ]*("[^"]*"|\'[^\']*\')')
_STYLE_RE = re.compile(
    r'[\t\n\r ]*([^:;\t\n\r ]*)[\t\n\r ]*:[\t\n\r ]*([^:;\t\n\r ]*)[\t\n\r ]*(?:;|\Z)'
)
_REMOVING_TAGS_RE = re.compile(r'(script|style|textarea|title)$', re.IGNORECASE)
_WS_PRESERVING_TAGS_RE = re.compile(r'pre$', re.IGNORECASE)
_NEWLINE_TAGS_RE = re.compile(r'br$', re.IGNORECASE)
_BLOCK_TAGS_RE = re.compile(
    r'/?(address|blockquote|dd|div|dl|dt|h[1-6]|hr|li|ol|p|pre|table|tr|ul)$',
    re.IGNORECASE)
_TAB_TAGS_RE = re.compile(r'(td|th)$', re.IGNORECASE)
_HTML_WHITESPACE_RE = re.compile(r'[ \t\r\n]+')
_TRAILING_NON_WHITESPACE_RE = re.compile(r'[^ \t\r\n]\Z')
_TRAILING_NON_NEWLINE_RE = re.compile(r'[^\n]\Z')
_LEADING_SPACE_RE = re.compile(r'^ ')
_PRESERVE_WHITESPACE_STYLES_RE = re.compile(r'(pre|pre-wrap|break-spaces)$',
                                            re.IGNORECASE)
_COLLAPSE_WHITESPACE_STYLES_RE = re.compile(r'(normal|nowrap)$', re.IGNORECASE)


def html_to_text(value):
  """Converts HTML to plain text.

  Args:
    value: HTML.

  Returns:
    Plain text.
  """
  if value is None:
    return ''
  html = str(value)
  if not isinstance(value, SanitizedHtml):
    return html
  text = ''
  start = 0
  removing_until = ''
  preserve_whitespace_stack = []

  def should_preserve_whitespace():
    if preserve_whitespace_stack:
      return preserve_whitespace_stack[-1][1]
    return False

  def get_style_preserves_whitespace(style):
    for match in _STYLE_RE.finditer(style):
      style_attribute = match.group(1)
      style_attribute_value = match.group(2)
      if style_attribute and style_attribute.lower() == 'white-space':
        if _PRESERVE_WHITESPACE_STYLES_RE.match(style_attribute_value):
          return True
        elif _COLLAPSE_WHITESPACE_STYLES_RE.match(style_attribute_value):
          return False

  def get_attributes_preserve_whitespace(attrs):
    if not attrs:
      return None

    for match in _ATTR_RE.finditer(attrs):
      attribute_name = match.group(1)
      if attribute_name and attribute_name.lower() == 'style':
        style = match.group(2)
        if style:
          # Strip quotes if the attribute value was quoted.
          if style[0] == '\'' or style[0] == '"':
            style = style[1:-1]
          return get_style_preserves_whitespace(style)
        return None

  def update_preserve_whitespace_stack(tag, attrs):
    if tag[0] == '/':
      tag = tag[1:]
      # Pop tags until we pop one that matches the current closing tag. We're
      # effectively automatically closing tags that aren't explicitly closed.
      while preserve_whitespace_stack and (
          preserve_whitespace_stack.pop()[0] != tag):
        pass
    elif _WS_PRESERVING_TAGS_RE.match(tag):
      preserve_whitespace_stack.append((tag, True))
    else:
      # For unspecified whitespace preservation, inherit from parent tag.
      preserve_whitespace = get_attributes_preserve_whitespace(attrs)
      if preserve_whitespace is None:
        preserve_whitespace = should_preserve_whitespace()

      preserve_whitespace_stack.append((tag, preserve_whitespace))

  for match in _TAG_RE.finditer(html):
    offset = match.start()
    tag = match.group(1).lower() if match.group(1) else None
    attrs = match.group(2)
    if not removing_until:
      chunk = html[start:offset]
      chunk = html_module.unescape(chunk)
      if not should_preserve_whitespace():
        chunk = _HTML_WHITESPACE_RE.sub(' ', chunk)
        if not _TRAILING_NON_WHITESPACE_RE.search(text):
          chunk = _LEADING_SPACE_RE.sub('', chunk)
      text += chunk
      if tag:
        if _REMOVING_TAGS_RE.match(tag):
          removing_until = '/' + tag
        elif _NEWLINE_TAGS_RE.match(tag):
          text += '\n'
        elif _BLOCK_TAGS_RE.match(tag):
          if _TRAILING_NON_NEWLINE_RE.search(text):
            text += '\n'
        elif _TAB_TAGS_RE.match(tag):
          text += '\t'

        if not _HTML5_VOID_ELEMENTS_RE.match('<' + tag + '>'):
          update_preserve_whitespace_stack(tag, attrs)
    elif removing_until == tag:
      removing_until = ''
    start = match.end()
  return text.replace('\u00A0', ' ')
  # LINT.ThenChange(
  #     ../../../../../javascript/template/soy/soyutils_usegoog.js:htmlToText,
  #     ../../java/com/google/template/soy/basicfunctions/HtmlToText.java)


def escape_css_string(value):
  return generated_sanitize.escape_css_string_helper(value)


def escape_html(value):
  html = _get_content_of_kind(value, CONTENT_KIND.HTML)
  if html is not None:
    approval = IActuallyUnderstandSoyTypeSafetyAndHaveSecurityApproval(
        'Persisting existing sanitization.')
    return SanitizedHtml(html, get_content_dir(value), approval=approval)

  approval = IActuallyUnderstandSoyTypeSafetyAndHaveSecurityApproval(
      'Escaped html is by nature sanitized.')
  return SanitizedHtml(generated_sanitize.escape_html_helper(value),
                       get_content_dir(value), approval=approval)


def escape_html_attribute(value):
  html = _get_content_of_kind(value, CONTENT_KIND.HTML)
  if html is not None:
    return generated_sanitize.normalize_html_helper(_strip_html_tags(html))

  return generated_sanitize.escape_html_helper(value)


def escape_html_html_attribute(value):
  return str(escape_html(value))


_NUMBER_RE = re.compile(r'\d*\.?\d+$')


def filter_number(value):
  if not _NUMBER_RE.match(str(value)):
    return _INNOCUOUS_OUTPUT
  return str(value)


def escape_html_attribute_nospace(value):
  html = _get_content_of_kind(value, CONTENT_KIND.HTML)
  if html is not None:
    return generated_sanitize.normalize_html_nospace_helper(
        _strip_html_tags(html))

  return generated_sanitize.escape_html_nospace_helper(value)


def escape_html_rcdata(value):
  html = _get_content_of_kind(value, CONTENT_KIND.HTML)
  if html is not None:
    return generated_sanitize.normalize_html_helper(html)

  return generated_sanitize.escape_html_helper(value)


def escape_js_regex(value):
  return generated_sanitize.escape_js_regex_helper(value)


def escape_js_string(value):
  if is_content_kind(value, CONTENT_KIND.JS_STR_CHARS):
    return value.content

  return generated_sanitize.escape_js_string_helper(value)


def escape_js_value(value):
  if value is None:
    # We output null for compatibility with Java, as it returns null from maps
    # where there is no corresponding key.
    return ' null '

  js = _get_content_of_kind(value, CONTENT_KIND.JS)
  if js is not None:
    return js

  # We surround values with spaces so that they can't be interpolated into
  # identifiers by accident.
  # We could use parentheses but those might be interpreted as a function call.
  # This matches the JS implementation in javascript/template/soy/soyutils.js.
  if isinstance(value, six.integer_types + (float, complex)):
    return ' ' + str(value) + ' '

  return "'" + generated_sanitize.escape_js_string_helper(value) + "'"


def escape_uri(value):
  return generated_sanitize.escape_uri_helper(value)


def filter_css_value(value):
  css = _get_content_of_kind(value, CONTENT_KIND.CSS)
  if css is not None:
    return _embed_css_into_html(css)

  if value is None:
    return ''

  return generated_sanitize.filter_css_value_helper(value)


def filter_html_attributes(value):
  # NOTE: Explicitly no support for SanitizedContentKind.HTML, since that is
  # meaningless in this context, which is generally *between* html attributes.
  if is_content_kind(value, CONTENT_KIND.ATTRIBUTES):
    return value.content

  # TODO(gboyer): Replace this with a runtime exception along with other
  # backends. http://b/19795203.
  return generated_sanitize.filter_html_attributes_helper(value)


def filter_html_element_name(value):
  # NOTE: We don't accept any SanitizedContent here. HTML indicates valid
  # PCDATA, not tag names. A sloppy developer shouldn't be able to cause an
  # exploit:
  # ... {let userInput}script src=http://evil.com/evil.js{/let} ...
  # ... {param tagName kind="html"}{$userInput}{/param} ...
  # ... <{$tagName}>Hello World</{$tagName}>
  return generated_sanitize.filter_html_element_name_helper(value)


def filter_image_data_uri(value):
  approval = IActuallyUnderstandSoyTypeSafetyAndHaveSecurityApproval(
      'Filtered URIs are by nature sanitized.')
  return SanitizedUri(
      generated_sanitize.filter_image_data_uri_helper(value), approval=approval)


def sms_to_uri(value):
  approval = IActuallyUnderstandSoyTypeSafetyAndHaveSecurityApproval(
      'Filtered URIs are by nature sanitized.')
  return SanitizedUri(
      generated_sanitize.filter_sms_uri_helper(value), approval=approval)


def filter_sip_uri(value):
  approval = IActuallyUnderstandSoyTypeSafetyAndHaveSecurityApproval(
      'Filtered URIs are by nature sanitized.')
  return SanitizedUri(
      generated_sanitize.filter_sip_uri_helper(value), approval=approval)


def filter_tel_uri(value):
  approval = IActuallyUnderstandSoyTypeSafetyAndHaveSecurityApproval(
      'Filtered URIs are by nature sanitized.')
  return SanitizedUri(
      generated_sanitize.filter_tel_uri_helper(value), approval=approval)


def filter_legacy_uri_behavior(value):
  approval = IActuallyUnderstandSoyTypeSafetyAndHaveSecurityApproval(
      'Filtered URIs are by nature sanitized.'
  )
  return SanitizedUri(
      generated_sanitize.filter_legacy_uri_behavior_helper(value),
      approval=approval,
  )


def filter_normalize_uri(value):
  uri = _get_content_of_kind(value, CONTENT_KIND.URI)
  if uri is None:
    uri = _get_content_of_kind(value, CONTENT_KIND.TRUSTED_RESOURCE_URI)
  if uri is None:
    return generated_sanitize.filter_normalize_uri_helper(value)

  return normalize_uri(uri)


def filter_normalize_media_uri(value):
  uri = _get_content_of_kind(value, CONTENT_KIND.URI)
  if uri is None:
    uri = _get_content_of_kind(value, CONTENT_KIND.TRUSTED_RESOURCE_URI)
  if uri is None:
    return generated_sanitize.filter_normalize_media_uri_helper(value)

  return normalize_uri(uri)


def filter_normalize_refresh_uri(value):
  return filter_normalize_uri(value).replace(';', '%3B')


def filter_trusted_resource_uri(value):
  uri = _get_content_of_kind(value, CONTENT_KIND.TRUSTED_RESOURCE_URI)
  if uri is not None:
    return uri
  return 'about:invalid#' + _INNOCUOUS_OUTPUT


def normalize_html(value):
  return generated_sanitize.normalize_html_helper(value)


def normalize_uri(value):
  return generated_sanitize.normalize_uri_helper(value)


def filter_html_script_phrasing_data(value):
  """See docs on soy.$$filterHtmlScriptPhrasingData in soyutils_usegoog.js."""

  def ascii_to_lower(c):
    if 'A' <= c <= 'Z':
      return c.lower()
    return c

  def match_prefix_ignore_case_past_end(needle, haystack, offset):
    chars_left = len(haystack) - offset
    chars_to_scan = min(len(needle), chars_left)
    for i in range(chars_to_scan):
      if needle[i] != ascii_to_lower(haystack[i + offset]):
        return False
    return True

  value_str = str(value)
  start = 0
  while True:
    lt = value_str.find('<', start)
    if lt == -1:
      break
    if match_prefix_ignore_case_past_end(
        '<!--', value_str, lt) or match_prefix_ignore_case_past_end(
            '</script', value_str, lt):
      return 'zSoyz'
    start = lt + 1
  return value_str


def filter_csp_nonce_value(value):
  return generated_sanitize.filter_csp_nonce_value_helper(value)


def whitespace_html_attributes(value):
  """Prepends value with a single space if it is not empty."""
  if isinstance(value, SanitizedHtmlAttribute):
    string_val = value.content
  else:
    string_val = value
  return (' '
          if string_val and not string_val.startswith(' ') else '') + string_val


############################
# Public Utility Functions #
############################


def get_content_dir(value):
  if isinstance(value, SanitizedContent):
    return value.content_dir

  return None


def is_content_kind(value, content_kind):
  return (isinstance(value, SanitizedContent) and
          value.content_kind == content_kind)


#############################
# Private Utility Functions #
#############################


def _get_content_of_kind(value, content_kind):
  """Gets string content from value if it's of kind content_kind or compatible.

  Args:
    value: Value of any type.
    content_kind: Desired content kind.

  Returns:
    String content of value or None if other kind.
  """
  if is_content_kind(value, content_kind):
    return value.content

  return None


def _get_content_kind(value):
  """Get human-readable name for the kind of value.

  Args:
    value: A input string.
  Returns:
    A string name represented the type of value.
  """
  if isinstance(value, SanitizedContent):
    return CONTENT_KIND.decodeKind(value.content_kind)
  else:
    return type(value)


def _strip_html_tags(value, tag_whitelist=None):
  """Strip any html tags not present on the whitelist.

  If there's a whitelist present, the handler will use a marker for whitelisted
  tags, strips all others, and then reinserts the originals.

  Args:
    value: The input string.
    tag_whitelist: A list of safe tag names.
  Returns:
    A string with non-whitelisted tags stripped.
  """
  if not tag_whitelist:
    # The second level (replacing '<' with '&lt;') ensures that non-tag uses of
    # '<' do not recombine into tags as in
    # '<<foo>script>alert(1337)</<foo>script>'
    return generated_sanitize._LT_REGEX.sub(
        '&lt;', generated_sanitize._HTML_TAG_REGEX.sub('', value))

  # Escapes '[' so that we can use [123] below to mark places where tags
  # have been removed.
  html = str(value).replace('[', '&#91;')

  # Consider all uses of '<' and replace whitelisted tags with markers like
  # [1] which are indices into a list of approved tag names.
  # Replace all other uses of < and > with entities.
  tags = []
  tag_handler = functools.partial(_tag_sub_handler, tag_whitelist, tags)
  html = generated_sanitize._HTML_TAG_REGEX.sub(tag_handler, html)

  # Escape HTML special characters. Now there are no '<' in html that could
  # start a tag.
  html = generated_sanitize.normalize_html_helper(html)

  # Discard any dead close tags and close any hanging open tags before
  # reinserting white listed tags.
  final_close_tags = _balance_tags(tags)

  # Now html contains no tags or less-than characters that could become
  # part of a tag via a replacement operation and tags only contains
  # approved tags.
  # Reinsert the white-listed tags.
  html = _REPLACEMENT_TAG_RE.sub(lambda match: tags[int(match.group(1))], html)

  # Close any still open tags.
  # This prevents unclosed formatting elements like <ol> and <table> from
  # breaking the layout of containing HTML.
  return html + final_close_tags


def _embed_css_into_html(css):
  """
  Make sure that tag boundaries are not broken by Safe CSS when embedded in an
  HTML <style> element.

  Args:
    css: Safe CSS content
  Returns:
    Embeddable safe CSS content
  """
  return _HTML_RAW_CONTENT_HAZARD_RE.sub(_defang_raw_content_hazard, css)


def _defang_raw_content_hazard(match):
  """Maps _HTML_RAW_CONTENT_HAZARD_RE matches to safe alternatives"""
  return _HTML_RAW_CONTENT_HAZARD_REPLACEMENTS[match.group(0)]


def _tag_sub_handler(tag_whitelist, tags, match):
  """Replace whitelisted tags with markers and update the tag list.

  Args:
    tag_whitelist: A list containing all whitelisted html tags.
    tags: The list of all whitelisted tags found in the text.
    match: The current match element with a subgroup containing the tag name.

  Returns:
    The replacement content, a index marker for whitelisted tags, or an empty
    string.
  """
  tag = match.group(0)
  name = match.group(1)
  if name:
    name = name.lower()

  # TODO(user): We need special handling to preserve HTML attribute "dir".
  # Similar to what we have in JsSrc:
  if name in tag_whitelist:
    start = '</' if tag[1] == '/' else '<'
    index = len(tags)
    tags.append(start + name + '>')
    return '[%d]' % index

  return ''


def _balance_tags(tags):
  """Throw out any close tags without an open tag.

  If {@code <table>} is used for formatting, embedded HTML shouldn't be able
  to use a mismatched {@code </table>} to break page layout.

  Args:
    tags: The list of all tags in this text.

  Returns:
    A string containing zero or more closed tags that close all elements that
    are opened in tags but not closed.
  """
  open_tags = []
  for i, tag in enumerate(tags):
    if tag[1] == '/':
      index = len(open_tags) - 1
      while index >= 0 and open_tags[index] != tag:
        index -= 1

      if index < 0:
        tags[i] = ''  # Drop close tag.
      else:
        tags[i] = ''.join(reversed(open_tags[index:]))
        del open_tags[index:]

    elif not _HTML5_VOID_ELEMENTS_RE.match(tag):
      open_tags.append('</' + tag[1:])

  return ''.join(reversed(open_tags))


#####################
# Sanitized Classes #
#####################


class IActuallyUnderstandSoyTypeSafetyAndHaveSecurityApproval:
  """An instance of this approval must be passed to any type conversion.

  The sanitized types are internal to Soy and they are allowed only in the code
  generated from templates and in internal Soy functions. External usage is not
  allowed and it will not be approved. Use SafeHtml types instead.

  """
  justification = None

  def __init__(self, justification=None):
    if justification:
      self.justification = justification


class CONTENT_KIND:
  (HTML, JS, JS_STR_CHARS, URI, TRUSTED_RESOURCE_URI, ATTRIBUTES, CSS,
   TEXT) = range(1, 9)

  @staticmethod
  def decodeKind(i):
    i -= 1
    return ['HTML', 'JS', 'JS_STR_CHARS', 'URI', 'TRUSTED_RESOURCE_URI',
            'ATTRIBUTES', 'CSS', 'TEXT'][i]


class DIR:
  LTR, NEUTRAL, RTL = (1, 0, -1)


class SanitizedContent(object):
  content_kind = None

  def __new__(cls, *args, **kwargs):
    if cls is SanitizedContent or not cls.content_kind:
      raise TypeError('SanitizedContent cannot be instantiated directly. '
                      'Instantiate a child class with a valid content_kind.')
    return object.__new__(cls)

  def __init__(self, content=None, content_dir=None, approval=None):
    if not isinstance(approval,
                      IActuallyUnderstandSoyTypeSafetyAndHaveSecurityApproval):
      raise TypeError('Caller does not have sanitization approval.')
    elif not approval.justification or len(approval.justification) < 20:
      raise TypeError('A justification of at least 20 characters must be'
                      'provided with the approval.')
    self.content = content
    self.content_dir = content_dir

  def __eq__(self, other):
    return isinstance(other, self.__class__) and self.__dict__ == other.__dict__

  def __ne__(self, other):
    return not self.__eq__(other)

  def __len__(self):
    return len(self.content)

  def __nonzero__(self):
    return bool(self.content)

  def __str__(self):
    return str(self.content)

  def __unicode__(self):
    return str(self.content)

  def __hash__(self):
    return hash((self.content, self.content_kind, self.content_dir))


class SanitizedCss(SanitizedContent):
  content_kind = CONTENT_KIND.CSS

  def __init__(self, content=None, approval=None):
    super(SanitizedCss, self).__init__(content, DIR.LTR, approval)


class SanitizedHtml(SanitizedContent):
  content_kind = CONTENT_KIND.HTML


class SanitizedHtmlAttribute(SanitizedContent):
  content_kind = CONTENT_KIND.ATTRIBUTES

  def __init__(self, content=None, approval=None):
    super(SanitizedHtmlAttribute, self).__init__(
        content, DIR.LTR, approval)


class SanitizedJs(SanitizedContent):
  content_kind = CONTENT_KIND.JS

  def __init__(self, content=None, approval=None):
    super(SanitizedJs, self).__init__(content, DIR.LTR, approval)


class SanitizedJsStrChars(SanitizedContent):
  content_kind = CONTENT_KIND.JS_STR_CHARS


class SanitizedUri(SanitizedContent):
  content_kind = CONTENT_KIND.URI

  def __init__(self, content=None, approval=None):
    super(SanitizedUri, self).__init__(content, DIR.LTR, approval)


class SanitizedTrustedResourceUri(SanitizedContent):
  content_kind = CONTENT_KIND.TRUSTED_RESOURCE_URI

  def __init__(self, content=None, approval=None):
    super(SanitizedTrustedResourceUri, self).__init__(content, DIR.LTR,
                                                      approval)

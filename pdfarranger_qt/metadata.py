# Copyright (C) 2020 Jerome Robert
#
# pdfarranger is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

""" PDF meta data edition """

import pikepdf
import gettext
import re
import json
import traceback
from datetime import datetime
from dateutil import parser
_ = gettext.gettext

# The producer property can be overridden by pikepdf
PRODUCER = '{http://ns.adobe.com/pdf/1.3/}Producer'
# Currently the only property which support lists as values. If you add more
# please implement a generic mechanism.
_CREATOR = '{http://purl.org/dc/elements/1.1/}creator'
_CREATED = '{http://ns.adobe.com/xap/1.0/}CreateDate'
_MODIFIED = '{http://ns.adobe.com/xap/1.0/}ModifyDate'
# List of supported meta data with their user representation
# see https://wwwimages2.adobe.com/content/dam/acom/en/devnet/xmp/pdfs/XMP%20SDK%20Release%20cc-2016-08/XMPSpecificationPart1.pdf
# if you want to add more
_LABELS = {
    '{http://purl.org/dc/elements/1.1/}title': _('Title'),
    '{http://purl.org/dc/elements/1.1/}description': _('Subject'),
    '{http://ns.adobe.com/pdf/1.3/}Keywords': _('Keywords'),
    PRODUCER: _('Producer'),
    _CREATOR: _('Creator'),
    '{http://ns.adobe.com/xap/1.0/}CreatorTool': _('Creator tool'),
    _CREATED: _('Created'),
    _MODIFIED: _('Modified'),
}


def _pikepdf_meta_is_valid(meta):
    """
    Return true if m is a valid PikePDF meta data value.
    PikePDF pass meta data to re.sub which only accept str or byte-like object.
    """
    if not isinstance(meta, list):
        meta = [meta]
    for s in meta:
        try:
            re.sub('', '', s)
        except TypeError:
            return False
    return True


def load_from_docinfo(meta, doc):
    """
    wrapper of pikepdf.models.PdfMetadata.load_from_docinfo with a workaround
    for https://github.com/pikepdf/pikepdf/issues/100 & 162
    """
    try:
        meta.load_from_docinfo(doc.docinfo)
    except (NotImplementedError, TypeError):
        # DocumentInfo cannot be loaded and will be lost. Not a that big issue.
        traceback.print_exc()


def _safeiter(elements):
    it = iter(elements)
    while True:
        try:
            yield next(it)
        except StopIteration:
            break
        except ValueError:
            traceback.print_exc()
        except KeyError:
            # Workaround for https://github.com/pdfarranger/pdfarranger/issues/1019
            pass


def merge_doc(metadata, input_docs):
    """Same as merge but with pikepdf.PDF object instead of files

    XMP metadata take precedence over equivalent docinfo metadata,
    metadata of later opened files are merged into these of earlier opened ones
    """
    r = metadata.copy()
    for doc in input_docs:
        with doc.open_metadata() as meta:
            for k, v in _safeiter(meta.items()):
                if not _pikepdf_meta_is_valid(v):
                    # workaround for https://github.com/pikepdf/pikepdf/issues/84
                    del meta[k]
                elif k not in r:
                    r[k] = v
            # workaround for https://github.com/pdfarranger/pdfarranger/issues/1168
            load_from_docinfo(meta, doc)
            for k, v in _safeiter(meta.items()):
                if not _pikepdf_meta_is_valid(v):
                    # workaround for https://github.com/pikepdf/pikepdf/issues/84
                    del meta[k]
                elif k not in r:
                    r[k] = v
    return r


def merge(metadata, input_files):
    """Merge current global metadata and each imported files meta data"""
    docs = [pikepdf.open(copyname, password=password) for copyname, password in input_files]
    return merge_doc(metadata, docs)


def _metatostr(value, name):
    """ Convert a meta data value from list to string if it's not a string """
    if isinstance(value, str):
        return value
    elif isinstance(value, list) and name == _CREATOR:
        if len(value) == 1:
            return _metatostr(value[0], name)
        else:
            return json.dumps(value)
    return ''


def _strtometa(value, name):
    try:
        r = json.loads(value) if name == _CREATOR else value
        if isinstance(r, list):
            return None if len(r) == 0 else r
        else:
            # r is a dict which is not supported so we revert back
            # to a plain string
            return value
    except json.decoder.JSONDecodeError:
        return value




from types import MappingProxyType as M

FORMAT_VERSION = 2
NAME = 'tool'
WINDOWS_OPTIONS = True

_s0 = M({'dest': 'verbose', 'type': 'int', 'multiple': False, 'nullable': False, 'choices': None, 'default': 0, 'required': False, 'action': 'count'})

def _bind0(values):
    return {'verbose': values['verbose']}

def _convert1(value, _spec):
    return value

_s1 = M({'dest': 'token', 'type': 'str', 'multiple': False, 'nullable': True, 'choices': None, 'default': None, 'required': False, 'action': 'value', '_convert': _convert1})

def _bind1(values):
    return {'token': values['token']}

def _convert2(value, _spec):
    return value

_s2 = M({'dest': 'url', 'type': 'str', 'multiple': False, 'nullable': False, 'choices': None, 'default': None, 'required': True, 'action': 'value', '_convert': _convert2})

_s3 = M({'dest': 'force', 'type': 'bool', 'multiple': False, 'nullable': False, 'choices': None, 'default': False, 'required': False, 'action': 'flag'})

def _convert4(value, _spec):
    return value

_s4 = M({'dest': 'name', 'type': 'str', 'multiple': False, 'nullable': False, 'choices': None, 'default': None, 'required': True, '_convert': _convert4})

def _bind2(values):
    return {'name': values['name'], 'url': values['url'], 'verbose': values['verbose'], 'token': values['token'], 'force': values['force']}


COMMANDS = M({'': (None, False, M({'verbose': 'verbose'}), (_s0, ), (), M({'--verbose': _s0, '-v': _s0, '/V': _s0}), M({'verbose': 0}), (), (), (), (), (), M({'remote': 'remote'}), _bind0, None, ), 'remote': (None, False, M({'token': 'token'}), (_s0, _s1, ), (), M({'--verbose': _s0, '-v': _s0, '/V': _s0, '--token': _s1, '-t': _s1, '/Token': _s1}), M({'verbose': 0, 'token': None}), (), (), (), (), (), M({'add': 'remote add', 'list': 'remote list'}), _bind1, None, ), 'remote add': ('examples.remote_cli.commands.remote:add', False, M({'name': 'name', 'url': 'url', 'verbose': 'verbose', 'token': 'token', 'force': 'force'}), (_s0, _s1, _s2, _s3, ), (_s4, ), M({'--verbose': _s0, '-v': _s0, '/V': _s0, '--token': _s1, '-t': _s1, '/Token': _s1, '--url': _s2, '-u': _s2, '/URL': _s2, '/U': _s2, '/u': _s2, '--force': _s3, '-f': _s3}), M({'verbose': 0, 'token': None, 'url': None, 'force': False}), ('url', ), (), (), (), (), M({}), _bind2, None, ), 'remote list': ('examples.remote_cli.commands.remote:list_remotes', False, M({'verbose': 'verbose'}), (_s0, _s1, ), (), M({'--verbose': _s0, '-v': _s0, '/V': _s0, '--token': _s1, '-t': _s1, '/Token': _s1}), M({'verbose': 0, 'token': None}), (), (), (), (), (), M({}), _bind0, None, )})

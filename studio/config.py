import copy
import json
from pathlib import Path


def merge(base, override):
    result = copy.deepcopy(base)
    for key, value in override.items():
        result[key] = merge(result[key], value) if isinstance(value, dict) and isinstance(result.get(key), dict) else copy.deepcopy(value)
    return result


def catalog(root):
    return json.loads((Path(root) / 'configs/catalog.json').read_text(encoding='utf-8'))


def resolve(root, product, model):
    data = catalog(root)
    if product not in data['products'] or model not in data['products'][product]['models']:
        raise ValueError('请选择有效的产品和型号。')
    family = data['products'][product]
    result = merge(data['common'], {k: v for k, v in family.items() if k != 'models'})
    result = merge(result, family['models'][model])
    result.update(product=product, model=model)
    for value in result.get('capabilities', {}).values():
        if value not in (True, False, None):
            raise ValueError('能力配置仅允许 true、false 或 null（未知）。')
    return result


def model_from_name(root, name):
    import re
    family = catalog(root)['products']['G系列']
    match = re.fullmatch(family['name_pattern'], name.strip(), re.IGNORECASE)
    if not match or match.group(1).upper() not in family['models']:
        raise ValueError('无法从眼镜名称识别型号，请输入完整名称，例如 DPVR G1_13E6（支持 G1/G3/G6）。')
    return match.group(1).upper()


def resolve_device(root, product, model, name):
    if product == 'G系列' or name.strip().upper().startswith('DPVR G'):
        model = model_from_name(root, name)
        product = 'G系列'
    return resolve(root, product, model)

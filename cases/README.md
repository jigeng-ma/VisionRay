# 用例目录与产品隔离

- `common/`：跨产品公共诊断用例及其 `registry.json`。
- `g_series/`：G系列业务用例及其 `registry.json`。G1/G3/G6 功能相同，共用脚本，不再拆成三份。
- `conftest.py`：所有产品共用的设备和 Appium fixture。
- `registry.json`：产品名称到独立注册表的目录映射。

新增其他产品时，建立独立目录（名称使用英文，例如 nova），新增该目录的 registry.json，并在根映射的 products 中加入产品配置名称和相对注册表路径。当前只创建已有实际用例的 G系列目录，其他产品有用例时再建立。

每轮只加载公共注册表与当前产品注册表。不同产品可以使用相同的 Sheet 名及编号；同一产品与公共用例之间不得重复。产品条目只能引用自身目录下的脚本。公共驱动和可复用流程放在 studio，不通过跨产品导入测试文件复用。

G系列配对：PAIR_001(G1)、PAIR_002(G3)、PAIR_003(G6)，均调用 g_series/test_pairing.py::test_bind；由用户输入完整蓝牙名称识别型号并过滤。

G系列登录注册：`G00_登录注册` 的 A 列 `C-L_###` 映射到 B 列 `AUTH_###`，执行 `g_series/test_auth.py::test_auth[AUTH_###]`。当前实现56条，其余行保持未实现；不要用空测试占位。账号准备、注销后的重新注册与密码恢复见 `docs/登录注册自动化.md`。

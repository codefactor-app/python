from setuptools import setup
from wheel.bdist_wheel import bdist_wheel


class BinaryWheel(bdist_wheel):
    def finalize_options(self):
        super().finalize_options()
        self.root_is_pure = False

    def get_tag(self):
        _, _, platform = super().get_tag()
        # The engine is an executable; it has no CPython ABI dependency.
        return "py3", "none", platform


setup(cmdclass={"bdist_wheel": BinaryWheel})

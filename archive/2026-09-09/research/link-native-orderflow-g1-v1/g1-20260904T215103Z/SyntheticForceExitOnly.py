"""SYNTHETIC_TEST_ONLY: dedicated force-exit plumbing case; not a research variant."""
from LinkTakerAbsorptionControlR1 import LinkTakerAbsorptionControlR1


class SyntheticForceExitOnly(LinkTakerAbsorptionControlR1):
    def populate_exit_trend(self, dataframe, metadata):
        dataframe['exit_long'] = 0
        return dataframe

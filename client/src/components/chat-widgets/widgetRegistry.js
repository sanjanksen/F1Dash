import QualifyingBattleWidget from './QualifyingBattleWidget.jsx'
import CornerAnalysisWidget from './CornerAnalysisWidget.jsx'
import RaceStoryWidget from './RaceStoryWidget.jsx'
import RacePaceBattleWidget from './RacePaceBattleWidget.jsx'
import CornerComparisonWidget from './CornerComparisonWidget.jsx'
import CircuitProfileWidget from './CircuitProfileWidget.jsx'
import DataTableWidget from './DataTableWidget.jsx'
import PitStopStrategyWidget from './PitStopStrategyWidget.jsx'
import DegTrendChart from './DegTrendChart.jsx'
import EnergyManagementWidget from './EnergyManagementWidget.jsx'
import ActiveAeroWidget from './ActiveAeroWidget.jsx'
import UndercutOvercutWidget from './UndercutOvercutWidget.jsx'
import MiniSectorHeatmapWidget from './MiniSectorHeatmapWidget.jsx'

// Single source of truth: widget-type string -> React component.
// To register a new widget: drop a component file next to this one and add a row here.
export const widgetRegistry = {
  qualifying_battle: QualifyingBattleWidget,
  corner_analysis: CornerAnalysisWidget,
  race_story: RaceStoryWidget,
  race_pace_battle: RacePaceBattleWidget,
  corner_comparison: CornerComparisonWidget,
  circuit_profile: CircuitProfileWidget,
  data_table: DataTableWidget,
  pit_stop_strategy: PitStopStrategyWidget,
  deg_trend_chart: DegTrendChart,
  energy_management: EnergyManagementWidget,
  active_aero: ActiveAeroWidget,
  undercut_overcut: UndercutOvercutWidget,
  mini_sector_heatmap: MiniSectorHeatmapWidget,
}

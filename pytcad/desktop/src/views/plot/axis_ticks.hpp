// PlotView's axes read like the QML viewport's matplotlib axes
// (NATIVE-DESKTOP-PLAN.md 16.2, decision 4): the tick locations and
// labels are ports of matplotlib 3.11's own code (ticker.py), operation
// for operation, at a GIVEN tick count.
//
//   linear_ticks      AutoLocator().tick_values  (MaxNLocator, steps
//                     [1, 2, 2.5, 5, 10], min_n_ticks 2)
//   log_major_ticks   LogLocator(subs=(1.0,), numticks=n).tick_values
//   log_minor_ticks   LogLocator(subs='auto', numticks=n).tick_values,
//                     including its fall-back to AutoLocator
//   scalar_labels     ScalarFormatter's set_locs + __call__ + get_offset,
//                     with the default rcParams: offset on (threshold 4),
//                     power limits (-5, 6), no mathtext, unicode minus
//   log_labels        LogFormatterSciNotation(base 10, labelOnlyBase=False,
//                     minor_thresholds (1, 0.4)): set_locs + __call__
//
// The tick COUNT matplotlib derives from the axis length in points and
// its font ("nbins='auto'"); the native app has its own rule (PlotView),
// so every function here takes the count. gui/tests/test_desktop_plot_ticks.py
// compares all of it with matplotlib itself. Qt-free.
#pragma once

#include <string>
#include <vector>

namespace tcad::desktop::plot {

std::vector<double> linear_ticks(double vmin, double vmax, int nbins);

// vmin and vmax must be positive (a log view always is); empty otherwise.
std::vector<double> log_major_ticks(double vmin, double vmax, int numticks);
std::vector<double> log_minor_ticks(double vmin, double vmax, int numticks);

// Labels for `locs` (every tick the locator returned, in view or not --
// matplotlib formats them all) on a view [view_min, view_max].
struct ScalarLabels {
    std::vector<std::string> labels;  // UTF-8, U+2212 for minus
    std::string offset_text;          // e.g. "1e−5", "+1e17", "1e−9+1.5"; "" for none
};
ScalarLabels scalar_labels(const std::vector<double>& locs, double view_min, double view_max);

struct LogLabel {
    bool shown = false;   // false: this tick is not labelled ("")
    bool decade = true;   // 10^exponent, else coeff x 10^exponent
    double coeff = 1.0;   // printed with %g
    int exponent = 0;
};
std::vector<LogLabel> log_labels(const std::vector<double>& locs, double view_min, double view_max);
// matplotlib's own string for a label, e.g. "$\mathdefault{10^{3}}$" --
// for the contract test; PlotView draws the superscript itself.
std::string mathtext(const LogLabel& label);

}  // namespace tcad::desktop::plot

"""
Oximetry Signal Processing & Hypoxic Burden Calculation Engine for desatNerd
Supports:
  - Multi-condition physiological artifact detection (SpO2 slew rates, pulse coupling, flatlines, dropouts)
  - Sleep-masked analysis (TST/SPT) when Compumedics XML annotations are available
  - High-precision oxygen desaturation detection (3% and 4% thresholds)
  - Detailed desaturation morphology (durations, depths, slopes, areas)
  - Conventional hypoxemia metrics (T90 %, T90 min, T88, T85, T80, ODI 3%, ODI 4%)
  - Literature hypoxic burden algorithms:
      1. Azarbarzin method (Hypoxic Burden, %min/h)
      2. REDTA method (de Chazal et al.: Respiratory Event Desaturation Transient Area, %h & %min/h)
      3. Kulkas method (Desaturation Severity DesSev, Recovery Severity RecSev, & Slope Dynamics)
"""

from typing import Any, Dict, List, Optional, Tuple
import numpy as np
import pandas as pd
from scipy.signal import find_peaks

from parsers import OximetryRecording


class OximetryEngine:

    @staticmethod
    def detect_artifacts(
        signal: np.ndarray,
        sr: float,
        pulse_signal: Optional[np.ndarray] = None,
        drop_below: float = 50.0,
        max_fall_rate_per_sec: float = 4.0,
        max_jump_per_sec: float = 6.0,
        pad_sec: float = 3.0,
        bridge_gap_sec: float = 3.0,
        max_flatline_sec: float = 15.0  # Catch frozen sensor / disconnect plateaus
    ) -> np.ndarray:
        sig = np.array(signal, dtype=np.float64).flatten()
        n = len(sig)
        if n == 0:
            return np.array([], dtype=bool)

        mask = np.zeros(n, dtype=bool)

        # 1. Hard Range & NaN Check
        mask |= np.isnan(sig) | (sig < drop_below) | (sig > 100.5)

        # 2. Physiological Slew-Rate Limits
        step_1s = max(1, int(round(1.0 * sr)))
        series_sig = pd.Series(sig)
        
        diff_1s = series_sig.diff(periods=step_1s).values
        mask |= (diff_1s < -max_fall_rate_per_sec)
        mask |= (diff_1s > max_jump_per_sec)

        step_3s = max(1, int(round(3.0 * sr)))
        diff_3s = series_sig.diff(periods=step_3s).values
        mask |= (diff_3s < -(max_fall_rate_per_sec * 2.5))

        # 3. Flatline Detection (Dead-flat runs < 92%)
        # In true physiology, SpO2 fluctuates; perfectly flat runs indicate a frozen or disconnected line
        flat_win = max(2, int(round(max_flatline_sec * sr)))
        rolling_std = series_sig.rolling(window=flat_win, center=True, min_periods=flat_win).std()
        
        # A std < 0.01 over >= 15 seconds at SpO2 < 92% is artificial
        flatline_mask = (rolling_std < 0.01) & (series_sig < 92.0)
        mask |= flatline_mask.fillna(False).values

        # 4. Pulse-Coupled Artifact Rejection
        if pulse_signal is not None and len(pulse_signal) == n:
            pls = np.array(pulse_signal, dtype=np.float64).flatten()
            valid_pls = pls[np.isfinite(pls)]
            
            # Guard: Only evaluate if a genuine, physiological pulse channel exists
            # (Ignores dummy channels, zero-filled arrays, or channels with median < 30)
            if len(valid_pls) > 0 and np.nanmedian(valid_pls) >= 30.0:
                pls_series = pd.Series(pls)
                
                # Severe loss of pulse signal or extreme tach/bradycardia limits
                pls_out_of_bounds = np.isnan(pls) | (pls < 25.0) | (pls > 240.0)
                
                # Unphysiological instantaneous jump (>40 bpm in 1 second)
                pls_jump = np.abs(pls_series.diff(periods=step_1s).fillna(0).values) > 40.0
                
                # Pulse flatline: ONLY reject if pulse is flat AND SpO2 is concurrently dropping/abnormal (<92%)
                # Normal sleep with steady HR at 97% SpO2 will NOT be rejected
                pls_std = pls_series.rolling(flat_win, center=True, min_periods=flat_win).std()
                pls_flat_desat = (pls_std < 0.01) & (series_sig < 92.0)
                
                mask |= (pls_out_of_bounds | pls_jump | pls_flat_desat.fillna(False).values)

        # 5. Bridge Gaps Between Nearby Artifacts
        bridge_samples = int(round(bridge_gap_sec * sr))
        if bridge_samples > 0:
            inv_mask = (~mask).astype(int)
            diff_inv = np.diff(np.concatenate(([0], inv_mask, [0])))
            island_starts = np.where(diff_inv == 1)[0]
            island_ends = np.where(diff_inv == -1)[0]

            for istart, iend in zip(island_starts, island_ends):
                if (iend - istart) <= bridge_samples:
                    if istart > 0 and iend < n:
                        mask[istart:iend] = True

        # 6. Symmetrical Boundary Padding
        pad_samples = max(1, int(round(pad_sec * sr)))
        padded_mask = (
            pd.Series(mask)
            .rolling(window=pad_samples * 2 + 1, center=True, min_periods=1)
            .max()
            .fillna(0)
            .astype(bool)
            .values
        )

        return padded_mask

    @staticmethod
    def preprocess_signal(
        signal: np.ndarray,
        sr: float,
        pulse_signal: Optional[np.ndarray] = None,
        drop_below: float = 50.0,
        max_fall_rate_per_sec: float = 4.0,
        max_jump_per_sec: float = 6.0,
        pad_sec: float = 3.0
    ) -> Tuple[np.ndarray, np.ndarray]:
        raw_sig = np.array(signal, dtype=np.float64).flatten()
        art_mask = OximetryEngine.detect_artifacts(
            raw_sig,
            sr,
            pulse_signal=pulse_signal,
            drop_below=drop_below,
            max_fall_rate_per_sec=max_fall_rate_per_sec,
            max_jump_per_sec=max_jump_per_sec,
            pad_sec=pad_sec
        )

        clean_sig = raw_sig.copy()
        clean_sig[art_mask] = np.nan

        # Linearly interpolate gaps <= 5 seconds; leaves wider gaps as NaN
        interp_limit = max(1, int(round(5.0 * sr)))
        series_clean = pd.Series(clean_sig).interpolate(method="linear", limit=interp_limit)

        # 1-second rolling median filter for high-frequency sensor jitter
        smooth_win = max(1, int(round(1.0 * sr)))
        smoothed = (
            series_clean.rolling(smooth_win, center=True, min_periods=1)
            .median()
            .values
        )
        return smoothed, art_mask

    @staticmethod
    def build_sleep_mask(sleep_epochs: Optional[List[int]], total_samples: int, sr: float) -> Optional[np.ndarray]:
        if not sleep_epochs or len(sleep_epochs) == 0:
            return None

        samples_per_epoch = int(round(30.0 * sr))
        is_sleep_epoch = [st in [1, 2, 3, 4] for st in sleep_epochs]
        expanded = np.repeat(is_sleep_epoch, samples_per_epoch)

        mask = np.zeros(total_samples, dtype=bool)
        limit = min(total_samples, len(expanded))
        mask[:limit] = expanded[:limit]
        return mask

    @staticmethod
    def build_spt_mask(sleep_epochs: Optional[List[int]], total_samples: int, sr: float) -> Tuple[Optional[np.ndarray], float, float]:
        if not sleep_epochs or len(sleep_epochs) == 0:
            return None, 0.0, 0.0

        non_wake = [i for i, st in enumerate(sleep_epochs) if st in [1, 2, 3, 4]]
        if not non_wake:
            return None, 0.0, 0.0

        first_sleep_idx = non_wake[0]
        last_sleep_idx = non_wake[-1]

        spt_start_sec = first_sleep_idx * 30.0
        spt_end_sec = (last_sleep_idx + 1) * 30.0

        mask = np.zeros(total_samples, dtype=bool)
        s_idx = max(0, int(round(spt_start_sec * sr)))
        e_idx = min(total_samples, int(round(spt_end_sec * sr)))
        mask[s_idx:e_idx] = True

        return mask, spt_start_sec, spt_end_sec

    @staticmethod
    def detect_desaturations(
        signal: np.ndarray,
        sr: float,
        art_mask: Optional[np.ndarray] = None,
        threshold: float = 3.0,
        min_duration: float = 5.0,
        max_duration: float = 120.0,
        baseline_win_sec: float = 300.0,
        baseline_quantile: float = 0.98,
        sleep_mask: Optional[np.ndarray] = None,
        spt_mask: Optional[np.ndarray] = None
    ) -> Tuple[List[Dict[str, Any]], np.ndarray]:
        sig = np.asarray(signal, dtype=np.float64).flatten()
        n = len(sig)
        if n == 0:
            return [], np.array([])

        if art_mask is None:
            art_mask = np.zeros(n, dtype=bool)

        # 1. Baseline calculation
        win_samples = max(1, int(round(baseline_win_sec * sr)))
        valid_series = pd.Series(np.where(art_mask, np.nan, sig))
        
        q_baseline = (
            valid_series
            .rolling(win_samples, min_periods=max(1, int(round(30.0 * sr))), center=True)
            .quantile(baseline_quantile)
            .bfill()
            .ffill()
            .values
        )

        short_win = max(1, int(round(90.0 * sr)))
        short_max = (
            valid_series
            .rolling(short_win, min_periods=1, center=True)
            .max()
            .bfill()
            .ffill()
            .values
        )
        baselines = np.maximum(q_baseline, short_max - 0.5)

        # 2. Trigger envelope
        drops = (baselines - sig) >= 1.5
        drops[art_mask | np.isnan(sig)] = False
        
        diff = np.diff(np.concatenate(([0], drops.astype(int), [0])))
        drop_starts = np.where(diff == 1)[0]
        drop_ends = np.where(diff == -1)[0]

        events = []
        last_event_end_idx = 0
        max_dur_samples = int(round(max_duration * sr))
        lookback_samples = int(round(45.0 * sr))
        search_extend_samples = int(round(60.0 * sr))
        max_recovery_search = int(round(90.0 * sr))

        for ds, de in zip(drop_starts, drop_ends):
            if ds < last_event_end_idx:
                ds = last_event_end_idx
            if ds >= de:
                continue

            # 3. Locate True Start
            earliest_lookback = max(last_event_end_idx, ds - lookback_samples)
            if ds > earliest_lookback:
                window_sig = sig[earliest_lookback : ds + 1]
                window_art = art_mask[earliest_lookback : ds + 1]
                valid_win = np.where(window_art, -np.inf, window_sig)
                true_start = earliest_lookback + int(np.nanargmax(valid_win))
            else:
                true_start = ds

            local_baseline = float(sig[true_start])
            if np.isnan(local_baseline) or local_baseline < 50.0:
                local_baseline = float(baselines[min(ds, n - 1)])

            # 4. Search for Nadir
            nadir_search_end = min(n, de + search_extend_samples)
            nadir_val = local_baseline
            nadir_idx = true_start

            for j in range(true_start, nadir_search_end):
                if np.isnan(sig[j]) or art_mask[j]:
                    break
                if sig[j] < nadir_val:
                    nadir_val = float(sig[j])
                    nadir_idx = j

            # 5. Search for Recovery
            recovery_idx = nadir_idx
            best_recovery_val = nadir_val
            target_baseline = min(local_baseline, baselines[nadir_idx]) - 0.5
            search_limit = min(n, nadir_idx + max_recovery_search)
            search_limit = min(search_limit, true_start + max_dur_samples)

            current_depth = local_baseline - nadir_val

            for j in range(nadir_idx, search_limit):
                if np.isnan(sig[j]) or art_mask[j]:
                    recovery_idx = j
                    break

                val = float(sig[j])

                # Track the peak reached during this resaturation
                if val > best_recovery_val:
                    best_recovery_val = val
                    recovery_idx = j

                current_rebound = val - nadir_val

                # Condition A: Clean return to baseline (within 0.5% of local or dynamic baseline)
                if val >= target_baseline or val >= (baselines[j] - 0.5):
                    recovery_idx = j
                    break

                # Condition B: Turnaround into the next event or plateau below baseline
                # If it has made a meaningful recovery (>= 50% of depth or >= 2.5%),
                # and has rolled over by >= 1.0% from the peak of this recovery:
                if current_rebound >= max(2.0, 0.50 * current_depth):
                    if (best_recovery_val - val) >= 1.0:
                        # recovery_idx remains locked at the sample of best_recovery_val
                        break
            else:
                recovery_idx = min(search_limit - 1, n - 1)

            if recovery_idx <= nadir_idx:
                recovery_idx = min(n - 1, nadir_idx + max(1, int(round(1.0 * sr))))

            actual_depth = local_baseline - nadir_val
            duration = (recovery_idx - true_start) / sr
            fall_duration = max(0.1, (nadir_idx - true_start) / sr)
            recov_duration = max(0.1, (recovery_idx - nadir_idx) / sr)

            # 6. Event Validation
            if actual_depth >= threshold and duration >= min_duration:
                ev_slice = art_mask[true_start : recovery_idx + 1]
                if np.sum(ev_slice) / max(1, len(ev_slice)) < 0.15:

                    is_in_tst = True
                    if sleep_mask is not None and len(sleep_mask) == n:
                        is_in_tst = bool(sleep_mask[nadir_idx])

                    is_in_spt = True
                    if spt_mask is not None and len(spt_mask) == n:
                        is_in_spt = bool(spt_mask[nadir_idx])

                    fall_seg = sig[true_start : nadir_idx + 1]
                    fall_area_sec = float(np.nansum(np.maximum(local_baseline - fall_seg, 0.0)) / sr)

                    recov_seg = sig[nadir_idx : recovery_idx + 1]
                    recov_area_sec = float(np.nansum(np.maximum(local_baseline - recov_seg, 0.0)) / sr)

                    total_area_sec = fall_area_sec + recov_area_sec

                    fall_slope = actual_depth / fall_duration
                    recovery_val = float(sig[recovery_idx])
                    recov_rise = max(0.0, recovery_val - nadir_val)
                    recov_slope = recov_rise / recov_duration

                    events.append({
                        "Event_ID": len(events) + 1,
                        "Start": true_start / sr,
                        "End": recovery_idx / sr,
                        "Duration": duration,
                        "Fall_Duration": fall_duration,
                        "Recovery_Duration": recov_duration,
                        "Baseline": local_baseline,
                        "Nadir": nadir_val,
                        "Depth": actual_depth,
                        "Fall_Slope": fall_slope,
                        "Recovery_Slope": recov_slope,
                        "Fall_Area_sec": fall_area_sec,
                        "Fall_Area_min": fall_area_sec / 60.0,
                        "Recovery_Area_sec": recov_area_sec,
                        "Recovery_Area_min": recov_area_sec / 60.0,
                        "Total_Area_sec": total_area_sec,
                        "Total_Area_min": total_area_sec / 60.0,
                        "Nadir_Time": nadir_idx / sr,
                        "Is_In_Sleep": is_in_tst,
                        "Is_In_TST": is_in_tst,
                        "Is_In_SPT": is_in_spt
                    })

                    last_event_end_idx = recovery_idx

        return events, baselines

    @staticmethod
    def calculate_t90_metrics(signal: np.ndarray, sr: float, art_mask: np.ndarray, sleep_mask: Optional[np.ndarray] = None) -> Dict[str, float]:
        sig = np.array(signal, dtype=np.float64).flatten()
        base_valid = ~art_mask & ~np.isnan(sig)

        if sleep_mask is not None and len(sleep_mask) == len(sig):
            valid = base_valid & sleep_mask
        else:
            valid = base_valid

        valid_count = np.sum(valid)
        valid_hours = (valid_count / sr) / 3600.0 if valid_count > 0 else 0.0
        valid_mins = valid_hours * 60.0

        if valid_count == 0:
            return {
                "Valid_Duration_Hours": 0.0, "Valid_Duration_Minutes": 0.0,
                "T90_Minutes": 0.0, "T90_Percent": 0.0,
                "T88_Minutes": 0.0, "T88_Percent": 0.0,
                "T85_Minutes": 0.0, "T85_Percent": 0.0,
                "T80_Minutes": 0.0, "T80_Percent": 0.0,
                "Artifact_Minutes": len(sig) / (sr * 60.0),
                "Artifact_Percent": 100.0
            }

        valid_sig = sig[valid]
        t90_samples = np.sum(valid_sig < 90.0)
        t88_samples = np.sum(valid_sig < 88.0)
        t85_samples = np.sum(valid_sig < 85.0)
        t80_samples = np.sum(valid_sig < 80.0)

        total_samples = len(sig)
        art_samples = np.sum(art_mask)

        return {
            "Valid_Duration_Hours": valid_hours,
            "Valid_Duration_Minutes": valid_mins,
            "T90_Minutes": (t90_samples / sr) / 60.0,
            "T90_Percent": (t90_samples / valid_count) * 100.0,
            "T88_Minutes": (t88_samples / sr) / 60.0,
            "T88_Percent": (t88_samples / valid_count) * 100.0,
            "T85_Minutes": (t85_samples / sr) / 60.0,
            "T85_Percent": (t85_samples / valid_count) * 100.0,
            "T80_Minutes": (t80_samples / sr) / 60.0,
            "T80_Percent": (t80_samples / valid_count) * 100.0,
            "Artifact_Minutes": (art_samples / sr) / 60.0,
            "Artifact_Percent": (art_samples / total_samples) * 100.0 if total_samples > 0 else 0.0
        }

    @staticmethod
    def calculate_azarbarzin_hypoxic_burden(
        signal: np.ndarray,
        sr: float,
        resp_events: List[Dict[str, Any]],
        analysis_duration_hours: float,
        desat_events: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, float]:
        sig = np.array(signal, dtype=np.float64).flatten()
        len_sig = len(sig)

        if len(resp_events) > 0:
            win_start_rel = -int(5 * sr)
            win_finish_rel = int(45 * sr)
            total_percent_mins = 0.0
            double_count_limit = 0

            for ev in resp_events:
                finish = int(np.round((ev["Start"] + ev["Duration"]) * sr)) - 1
                if finish - int(100 * sr) > 0 and finish + win_finish_rel < len_sig:
                    baseline = np.nanmax(sig[finish - int(100 * sr) : finish + 1])
                    calc_start = max(finish + win_start_rel, double_count_limit)
                    calc_end = finish + win_finish_rel

                    if calc_end > calc_start:
                        segment = sig[calc_start : calc_end + 1]
                        area = np.nansum(np.maximum(baseline - segment, 0.0)) / (60.0 * sr)
                        total_percent_mins += float(area)
                        double_count_limit = calc_end

            hb_rate = total_percent_mins / analysis_duration_hours if analysis_duration_hours > 0 else 0.0
            return {
                "Azarbarzin_HB_Total_PercentMin": total_percent_mins,
                "Azarbarzin_HB_Rate_PercentMin_hr": hb_rate,
                "Azarbarzin_Event_Count": len(resp_events),
                "Azarbarzin_Method": "Respiratory Event Linked (Azarbarzin 2019)"
            }

        elif desat_events and len(desat_events) > 0:
            total_percent_mins = sum(ev["Total_Area_min"] for ev in desat_events)
            hb_rate = total_percent_mins / analysis_duration_hours if analysis_duration_hours > 0 else 0.0
            return {
                "Azarbarzin_HB_Total_PercentMin": total_percent_mins,
                "Azarbarzin_HB_Rate_PercentMin_hr": hb_rate,
                "Azarbarzin_Event_Count": len(desat_events),
                "Azarbarzin_Method": "Desaturation-Derived (Standalone SpO2)"
            }
        else:
            return {
                "Azarbarzin_HB_Total_PercentMin": 0.0,
                "Azarbarzin_HB_Rate_PercentMin_hr": 0.0,
                "Azarbarzin_Event_Count": 0,
                "Azarbarzin_Method": "None (No Events Detected)"
            }

    @staticmethod
    def calculate_redta_hypoxic_burden(
        signal: np.ndarray,
        sr: float,
        resp_events: List[Dict[str, Any]],
        analysis_duration_hours: float,
        desat_events: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, float]:
        sig = np.array(signal, dtype=np.float64).flatten()
        len_sig = len(sig)

        if len(resp_events) > 0:
            total_area_sec = 0.0
            for ev in resp_events:
                t_start = ev.get("Start", 0.0)
                dur = ev.get("Duration", 20.0)
                t_mid = t_start + 0.5 * dur
                t_win_end = t_mid + 2.5 * dur

                s_idx = max(0, int(round(t_mid * sr)))
                e_idx = min(len_sig - 1, int(round(t_win_end * sr)))

                if e_idx > s_idx:
                    seg = sig[s_idx : e_idx + 1]
                    area_sec = np.nansum(np.maximum(100.0 - seg, 0.0)) / sr
                    total_area_sec += float(area_sec)

            redta_pct_hours = total_area_sec / 3600.0
            redta_rate = (total_area_sec / 60.0) / analysis_duration_hours if analysis_duration_hours > 0 else 0.0
            return {
                "REDTA_Total_PercentHours": redta_pct_hours,
                "REDTA_Rate_PercentMin_hr": redta_rate,
                "REDTA_Event_Count": len(resp_events),
                "REDTA_Method": "Respiratory Event Linked (de Chazal 2021)"
            }
        elif desat_events and len(desat_events) > 0:
            total_area_sec = 0.0
            for ev in desat_events:
                t_start = ev["Start"]
                dur = ev["Duration"]
                t_win_end = t_start + 2.5 * dur

                s_idx = max(0, int(round(t_start * sr)))
                e_idx = min(len_sig - 1, int(round(t_win_end * sr)))

                if e_idx > s_idx:
                    seg = sig[s_idx : e_idx + 1]
                    area_sec = np.nansum(np.maximum(100.0 - seg, 0.0)) / sr
                    total_area_sec += float(area_sec)

            redta_pct_hours = total_area_sec / 3600.0
            redta_rate = (total_area_sec / 60.0) / analysis_duration_hours if analysis_duration_hours > 0 else 0.0
            return {
                "REDTA_Total_PercentHours": redta_pct_hours,
                "REDTA_Rate_PercentMin_hr": redta_rate,
                "REDTA_Event_Count": len(desat_events),
                "REDTA_Method": "Desaturation-Derived (Standalone SpO2)"
            }
        else:
            return {
                "REDTA_Total_PercentHours": 0.0,
                "REDTA_Rate_PercentMin_hr": 0.0,
                "REDTA_Event_Count": 0,
                "REDTA_Method": "None (No Events Detected)"
            }

    @staticmethod
    def calculate_kulkas_desaturation_severity(
        desat_events: List[Dict[str, Any]],
        analysis_duration_hours: float
    ) -> Dict[str, float]:
        if not desat_events or analysis_duration_hours <= 0:
            return {
                "Kulkas_DesSev_PercentMin_hr": 0.0,
                "Kulkas_RecSev_PercentMin_hr": 0.0,
                "Kulkas_Total_Severity_PercentMin_hr": 0.0,
                "Kulkas_Mean_Fall_Slope": 0.0,
                "Kulkas_Mean_Recovery_Slope": 0.0,
                "Kulkas_Mean_Desat_Area_min": 0.0,
                "Kulkas_Event_Count": 0
            }

        total_fall_area_min = sum(ev["Fall_Area_min"] for ev in desat_events)
        total_recov_area_min = sum(ev["Recovery_Area_min"] for ev in desat_events)
        total_area_min = sum(ev["Total_Area_min"] for ev in desat_events)

        fall_slopes = [ev["Fall_Slope"] for ev in desat_events if not np.isnan(ev["Fall_Slope"])]
        recov_slopes = [ev["Recovery_Slope"] for ev in desat_events if not np.isnan(ev["Recovery_Slope"])]

        return {
            "Kulkas_DesSev_PercentMin_hr": total_fall_area_min / analysis_duration_hours,
            "Kulkas_RecSev_PercentMin_hr": total_recov_area_min / analysis_duration_hours,
            "Kulkas_Total_Severity_PercentMin_hr": total_area_min / analysis_duration_hours,
            "Kulkas_Mean_Fall_Slope": float(np.mean(fall_slopes)) if fall_slopes else 0.0,
            "Kulkas_Mean_Recovery_Slope": float(np.mean(recov_slopes)) if recov_slopes else 0.0,
            "Kulkas_Mean_Desat_Area_min": float(np.mean([ev["Total_Area_min"] for ev in desat_events])),
            "Kulkas_Event_Count": len(desat_events)
        }

    @staticmethod
    def analyze_recording(
        recording: OximetryRecording,
        threshold: float = 3.0,
        min_duration: float = 5.0,
        max_duration: float = 120.0,
        baseline_win_sec: float = 300.0,
        baseline_quantile: float = 0.98,
        analysis_window_type: str = "SPT"
    ) -> Dict[str, Any]:
        sr = recording.fs
        raw_sig = recording.spo2_raw
        n_samples = len(raw_sig)

        # 1. Preprocess & Artifact Detection (passing pulse_raw to couple signal stability)
        clean_sig, art_mask = OximetryEngine.preprocess_signal(
            raw_sig,
            sr,
            pulse_signal=recording.pulse_raw
        )

        # 2. Build Sleep Masks (TST and SPT) if Sleep Stages are Loaded
        sleep_mask = OximetryEngine.build_sleep_mask(recording.sleep_epochs, n_samples, sr)
        spt_mask, spt_start_sec, spt_end_sec = OximetryEngine.build_spt_mask(recording.sleep_epochs, n_samples, sr)
        has_sleep_stages = (sleep_mask is not None and spt_mask is not None)

        # 3. Determine Active Analysis Window & Hours
        total_hours = n_samples / (sr * 3600.0)

        if analysis_window_type == "SPT" and has_sleep_stages:
            spt_hours = recording.sleep_summary.get("SPT_Hours", 0.0)
            analysis_hours = spt_hours if spt_hours > 0 else (np.sum(spt_mask) / (sr * 3600.0))
            window_mask = spt_mask
        elif analysis_window_type == "TST" and has_sleep_stages:
            tst_hours = recording.sleep_summary.get("TST_Hours", 0.0)
            analysis_hours = tst_hours if tst_hours > 0 else (np.sum(sleep_mask) / (sr * 3600.0))
            window_mask = sleep_mask
        else:
            analysis_window_type = "TRT"
            base_t90 = OximetryEngine.calculate_t90_metrics(clean_sig, sr, art_mask)
            analysis_hours = base_t90["Valid_Duration_Hours"] if base_t90["Valid_Duration_Hours"] > 0 else total_hours
            window_mask = None

        if analysis_hours <= 0:
            analysis_hours = total_hours if total_hours > 0 else 1.0

        # T90 Metrics computed within the active analysis window
        t90_metrics = OximetryEngine.calculate_t90_metrics(clean_sig, sr, art_mask, window_mask)

        # 4. Desaturation Detection
        desat_events_main, baselines = OximetryEngine.detect_desaturations(
            clean_sig, sr, art_mask,
            threshold=threshold,
            min_duration=min_duration,
            max_duration=max_duration,
            baseline_win_sec=baseline_win_sec,
            baseline_quantile=baseline_quantile,
            sleep_mask=sleep_mask,
            spt_mask=spt_mask
        )

        desat_events_3pct, _ = OximetryEngine.detect_desaturations(
            clean_sig, sr, art_mask,
            threshold=3.0, min_duration=min_duration, max_duration=max_duration,
            baseline_win_sec=baseline_win_sec, baseline_quantile=baseline_quantile,
            sleep_mask=sleep_mask,
            spt_mask=spt_mask
        )
        desat_events_4pct, _ = OximetryEngine.detect_desaturations(
            clean_sig, sr, art_mask,
            threshold=4.0, min_duration=min_duration, max_duration=max_duration,
            baseline_win_sec=baseline_win_sec, baseline_quantile=baseline_quantile,
            sleep_mask=sleep_mask,
            spt_mask=spt_mask
        )

        # Filter events according to chosen window
        if analysis_window_type == "SPT" and has_sleep_stages:
            desat_events_main = [e for e in desat_events_main if e.get("Is_In_SPT", True)]
            desat_events_3pct = [e for e in desat_events_3pct if e.get("Is_In_SPT", True)]
            desat_events_4pct = [e for e in desat_events_4pct if e.get("Is_In_SPT", True)]
            resp_events = [e for e in recording.respiratory_events if spt_start_sec <= (e.get("Start", 0.0) + e.get("Duration", 0.0)/2.0) <= spt_end_sec]
        elif analysis_window_type == "TST" and has_sleep_stages:
            desat_events_main = [e for e in desat_events_main if e.get("Is_In_TST", True)]
            desat_events_3pct = [e for e in desat_events_3pct if e.get("Is_In_TST", True)]
            desat_events_4pct = [e for e in desat_events_4pct if e.get("Is_In_TST", True)]
            resp_events = [e for e in recording.respiratory_events if sleep_mask[min(n_samples - 1, int(round((e.get("Start", 0.0) + e.get("Duration", 0.0)/2.0) * sr)))]]
        else:
            resp_events = recording.respiratory_events

        # 5. Conventional Indices
        odi_3 = len(desat_events_3pct) / analysis_hours if analysis_hours > 0 else 0.0
        odi_4 = len(desat_events_4pct) / analysis_hours if analysis_hours > 0 else 0.0

        valid_filter = ~art_mask & ~np.isnan(clean_sig)
        if window_mask is not None:
            valid_filter = valid_filter & window_mask

        valid_sig = clean_sig[valid_filter]
        mean_spo2 = float(np.nanmean(valid_sig)) if len(valid_sig) > 0 else np.nan
        min_spo2 = float(np.nanmin(valid_sig)) if len(valid_sig) > 0 else np.nan
        baseline_spo2 = float(np.nanmedian(baselines)) if len(baselines) > 0 else np.nan

        # 6. Desaturation Morphology Summary Statistics
        if desat_events_main:
            mean_dur = float(np.mean([e["Duration"] for e in desat_events_main]))
            mean_depth = float(np.mean([e["Depth"] for e in desat_events_main]))
            mean_fall_slope = float(np.mean([e["Fall_Slope"] for e in desat_events_main]))
            mean_recov_slope = float(np.mean([e["Recovery_Slope"] for e in desat_events_main]))
            mean_total_area_sec = float(np.mean([e["Total_Area_sec"] for e in desat_events_main]))
            mean_total_area_min = float(np.mean([e["Total_Area_min"] for e in desat_events_main]))
        else:
            mean_dur = 0.0
            mean_depth = 0.0
            mean_fall_slope = 0.0
            mean_recov_slope = 0.0
            mean_total_area_sec = 0.0
            mean_total_area_min = 0.0

        # 7. Sleep Apnea Specific Hypoxic Burden Algorithms
        azarbarzin_res = OximetryEngine.calculate_azarbarzin_hypoxic_burden(
            clean_sig, sr, resp_events, analysis_hours, desat_events_main
        )
        redta_res = OximetryEngine.calculate_redta_hypoxic_burden(
            clean_sig, sr, resp_events, analysis_hours, desat_events_main
        )
        kulkas_res = OximetryEngine.calculate_kulkas_desaturation_severity(
            desat_events_main, analysis_hours
        )

        return {
            "File_Name": recording.file_name,
            "File_Path": recording.file_path,
            "Device_Type": recording.device_type,
            "Patient_ID": recording.patient_id,
            "Sampling_Rate_Hz": sr,
            "Total_Duration_Hours": total_hours,
            "Analysis_Duration_Hours": analysis_hours,
            "Analysis_Window_Type": analysis_window_type,
            "Annotation_File": recording.annotation_file_loaded,
            "Has_Sleep_Stages": has_sleep_stages,
            "Sleep_Summary": recording.sleep_summary,
            "SPT_Start_sec": spt_start_sec,
            "SPT_End_sec": spt_end_sec,

            # General Oximetry
            "Baseline_SpO2": baseline_spo2,
            "Mean_SpO2": mean_spo2,
            "Min_SpO2": min_spo2,

            # Desaturation Indices
            "Desaturation_Threshold": threshold,
            "Desaturation_Count": len(desat_events_main),
            "ODI_Selected": len(desat_events_main) / analysis_hours if analysis_hours > 0 else 0.0,
            "ODI_3pct": odi_3,
            "ODI_4pct": odi_4,

            # Morphology
            "Mean_Desat_Duration_sec": mean_dur,
            "Mean_Desat_Depth_pct": mean_depth,
            "Mean_Fall_Slope_pct_s": mean_fall_slope,
            "Mean_Recovery_Slope_pct_s": mean_recov_slope,
            "Mean_Desat_Area_pct_sec": mean_total_area_sec,
            "Mean_Desat_Area_pct_min": mean_total_area_min,

            # Conventional Hypoxemia (T90 family)
            "T90_Percent": t90_metrics["T90_Percent"],
            "T90_Minutes": t90_metrics["T90_Minutes"],
            "T88_Percent": t90_metrics["T88_Percent"],
            "T88_Minutes": t90_metrics["T88_Minutes"],
            "T85_Percent": t90_metrics["T85_Percent"],
            "T85_Minutes": t90_metrics["T85_Minutes"],
            "T80_Percent": t90_metrics["T80_Percent"],
            "T80_Minutes": t90_metrics["T80_Minutes"],
            "Artifact_Percent": t90_metrics["Artifact_Percent"],
            "Artifact_Minutes": t90_metrics["Artifact_Minutes"],

            # Hypoxic Burden Algorithms
            "Azarbarzin_HB_pctmin_hr": azarbarzin_res["Azarbarzin_HB_Rate_PercentMin_hr"],
            "Azarbarzin_HB_Total_pctmin": azarbarzin_res["Azarbarzin_HB_Total_PercentMin"],
            "Azarbarzin_Method": azarbarzin_res["Azarbarzin_Method"],

            "REDTA_pct_hours": redta_res["REDTA_Total_PercentHours"],
            "REDTA_Rate_pctmin_hr": redta_res["REDTA_Rate_PercentMin_hr"],
            "REDTA_Method": redta_res["REDTA_Method"],

            "Kulkas_DesSev_pctmin_hr": kulkas_res["Kulkas_DesSev_PercentMin_hr"],
            "Kulkas_RecSev_pctmin_hr": kulkas_res["Kulkas_RecSev_PercentMin_hr"],
            "Kulkas_Total_Severity_pctmin_hr": kulkas_res["Kulkas_Total_Severity_PercentMin_hr"],
            "Kulkas_Mean_Fall_Slope": kulkas_res["Kulkas_Mean_Fall_Slope"],
            "Kulkas_Mean_Recovery_Slope": kulkas_res["Kulkas_Mean_Recovery_Slope"],

            # Arrays for UI & Visualization
            "raw_signal": raw_sig,
            "clean_signal": clean_sig,
            "artifact_mask": art_mask,
            "baseline_curve": baselines,
            "sleep_mask": sleep_mask,
            "spt_mask": spt_mask,
            "sleep_epochs": recording.sleep_epochs,
            "desaturation_events": desat_events_main,
            "desat_events_3pct": desat_events_3pct,
            "desat_events_4pct": desat_events_4pct
        }
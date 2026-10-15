#include "dolly_overlay_panel.hpp"
#include "dolly_lite.hpp"
#include "dolly_replay_events.hpp"
#include "dolly_visualization_runtime.hpp"
#include "dolly_ui_tokens_generated.hpp"
#include "imgui_internal.h"
#include <shellapi.h>
#include <algorithm>
#include <cstdlib>
#include <cstdio>
#include <cstring>
#include <climits>
namespace dolly {
static ImVec4 color(unsigned rgb) {
    return ImVec4(float((rgb >> 16) & 255) / 255, float((rgb >> 8) & 255) / 255,
                  float(rgb & 255) / 255, 1);
}
bool lite_mode_requested() noexcept {
    // Historical internal name: there is now one standard Dolly interface.
    // Keep the camera transport ABI and authored data compatible.
    return true;
}
static bool camera_request(EditorAction action, double value, const EditorCameraList& list) {
    CameraPose request{};
    request[0] = list.revision;
    return editor_enqueue(action, value, &request);
}
bool OverlayPanel::shader_notice_visible(const EditorSnapshot& state) const noexcept {
    EditorLiteReplayInfo info{};
    return state.focused && editor_lite_replay_info(info) && (info.flags & 4);
}
void OverlayPanel::draw_shader_notice() {
    const auto size = ImGui::GetIO().DisplaySize;
    const float s = panel_scale;
    const float inset = 24 * s;
    ImGui::SetNextWindowPos(ImVec2(size.x * .5f, size.y * .75f), ImGuiCond_Always, ImVec2(.5f, 1));
    ImGui::SetNextWindowSize(ImVec2(std::min(360 * s, std::max(1.f, size.x - 2 * inset)), 0));
    ImGui::SetNextWindowBgAlpha(.96f);
    ImGui::PushStyleColor(ImGuiCol_WindowBg, color(ui::PANEL));
    ImGui::PushStyleVar(ImGuiStyleVar_WindowPadding, ImVec2(16 * s, 12 * s));
    ImGui::PushStyleVar(ImGuiStyleVar_WindowRounding, 6 * s);
    ImGui::PushStyleVar(ImGuiStyleVar_ItemSpacing, ImVec2(8 * s, 6 * s));
    ImGui::Begin("##shader-loading", nullptr, ImGuiWindowFlags_NoDecoration |
        ImGuiWindowFlags_AlwaysAutoResize | ImGuiWindowFlags_NoInputs |
        ImGuiWindowFlags_NoSavedSettings | ImGuiWindowFlags_NoFocusOnAppearing);
    ImGui::PushFont(heading_font);
    ImGui::TextUnformatted("Loading shaders");
    ImGui::PopFont();
    ImGui::PushStyleColor(ImGuiCol_Text, color(ui::MUTED));
    ImGui::PushTextWrapPos(0);
    ImGui::TextUnformatted("Your replay will open automatically.");
    ImGui::PopTextWrapPos();
    ImGui::PopStyleColor();
    ImGui::End();
    ImGui::PopStyleVar(3);
    ImGui::PopStyleColor();
}
bool OverlayPanel::lite_campaths_visible(const EditorSnapshot& state) const noexcept {
    return lite_mode_ && state.enabled && state.focused && state.owner == EditorOwner::Panel;
}
void OverlayPanel::draw_lite_campaths(const EditorSnapshot& state) {
    using namespace ImGui;
    auto& io = GetIO();
    float s = panel_scale;
    if (!lite_campaths_visible(state))
        return;
    const bool compact = io.DisplaySize.x < 900 * s || io.DisplaySize.y < 650 * s;
    if (compact && state.owner == EditorOwner::Panel && !compact_paths_) return;
    EditorCameraList list{};
    EditorLiteReplayInfo info{};
    bool have_list = editor_camera_list(list) && list.total == state.camera_count;
    bool have_info = editor_lite_replay_info(info);
    bool matching = have_info && have_list && info.revision == list.revision &&
                    info.first == list.first && info.count == list.count;
    auto flags = ImGuiWindowFlags_NoTitleBar | ImGuiWindowFlags_NoScrollbar | ImGuiWindowFlags_NoScrollWithMouse;
    if (!layout_editing_) flags |= ImGuiWindowFlags_NoResize | ImGuiWindowFlags_NoMove;
    if (state.owner != EditorOwner::Panel)
        flags |= ImGuiWindowFlags_NoInputs;
    if (have_list) {
        bool just_added = false;
        const bool changed_block = lite_arrive_first_ != list.first;
        if (lite_arrive_revision_ != list.revision || lite_arrive_first_ != list.first) {
            if (lite_arrive_first_ != list.first) {
                std::fill(std::begin(lite_arrive_editing_), std::end(lite_arrive_editing_), false);
                std::fill(std::begin(lite_bank_editing_),std::end(lite_bank_editing_),false);
                bank_release_pending_=false;
            }
            lite_arrive_revision_ = list.revision;
            lite_arrive_first_ = list.first;
            for (unsigned i = 0; i < list.count; ++i) {
                if (!lite_arrive_editing_[i])
                    lite_arrive_drafts_[i] = float(list.rows[i].time);
                if (!lite_bank_editing_[i]) lite_bank_drafts_[i] = float(list.rows[i].roll);
            }
        }
        const float usable_bottom = io.DisplaySize.y - lite_timeline_height() - 32 * s;
        const float maximum_height = std::max(220 * s, usable_bottom - 16 * s);
        const bool full_width = compact && state.owner == EditorOwner::Panel;
        const float camera_width=CalcTextSize("Camera 64").x+6*s;
        const float arrive_width=std::max(CalcTextSize("Arrive / s").x,CalcTextSize("9999.99").x)+6*s;
        const float aspect_width=CalcTextSize("Aspect").x+6*s;
        const float bank_width=std::max(CalcTextSize("Bank").x,CalcTextSize("-180.0").x)+6*s;
        const float minimum_width=32*s+camera_width+arrive_width+aspect_width+bank_width;
        const float panel_width = full_width ? io.DisplaySize.x - 32 * s : std::max(252*s,minimum_width);
        const float controls_height = 4 * (GetFrameHeight() + 6 * s) + 6 * s + 1;
        const float header_height = GetTextLineHeight() + 4 * s;
        const float row_height = GetTextLineHeight() + 8 * s;
        const float panel_height = full_width ? maximum_height :
            std::min(maximum_height, list.total ? std::clamp(64 * s + controls_height + header_height + row_height * list.count,
                                                           280 * s, 510 * s) : 320 * s);
        // Anchor before Begin: moving an auto-sized window after Begin shifts
        // its content, but leaves the background and clip rectangles behind.
        const ImVec2 position(16 * s, full_width ? 16 * s : usable_bottom - panel_height);
        const bool focus_layout = !layout_custom_;
        SetNextWindowPos(outer_position_pending_[0] ? outer_position_[0] : position, (outer_position_pending_[0] || focus_layout || (layout_reset_ & 2)) ? ImGuiCond_Always : ImGuiCond_FirstUseEver);
        outer_position_pending_[0]=false;
        const auto* previous_sidebar=FindWindowByName("##lite-campaths");
        // Adopt the narrower default once for older layouts, preserving their
        // position and height. Subsequent user widths remain authoritative.
        if(!sidebar_width_current_ && !full_width) {sidebar_width_pending_=panel_width;sidebar_width_current_=true;MarkIniSettingsDirty();}
        SetNextWindowSize(ImVec2(sidebar_width_pending_>=0 ? sidebar_width_pending_ : panel_width,
                                sidebar_width_pending_>=0 && previous_sidebar ? previous_sidebar->Size.y : panel_height),
                         (sidebar_width_pending_>=0 || focus_layout || (layout_reset_ & 2)) ? ImGuiCond_Always : ImGuiCond_FirstUseEver);
        sidebar_width_pending_=-1;
        layout_reset_ &= ~2u;
        SetNextWindowSizeConstraints(ImVec2(std::min(minimum_width, panel_width), std::min(280 * s, maximum_height)),
                                    ImVec2(full_width ? panel_width : std::min(360*s,io.DisplaySize.x - 32 * s), maximum_height));
        PushStyleVar(ImGuiStyleVar_WindowPadding, ImVec2(8 * s, 12 * s));
        PushStyleVar(ImGuiStyleVar_ItemSpacing, ImVec2(8 * s, 6 * s));
        PushStyleVar(ImGuiStyleVar_WindowRounding, 6 * s);
        PushStyleVar(ImGuiStyleVar_FrameRounding, 4 * s);
        PushStyleVar(ImGuiStyleVar_FrameBorderSize, 0);
        Begin("##lite-campaths", nullptr, flags);
        constrain_panel();
        panel_handle("Drag campaths");
        if (have_camera_total_ && list.total > previous_camera_total_) {
            animated_camera_ = state.selected_camera < list.total ? state.selected_camera : list.total - 1;
            camera_added_at_ = GetTime();
            just_added = true;
            if (animated_camera_ >= list.first + list.count)
                camera_request(EditorAction::CameraPage, std::min((animated_camera_ / kEditorCameraListCount) * kEditorCameraListCount,
                    list.total > kEditorCameraListCount ? list.total - kEditorCameraListCount : 0u), list);
        }
        previous_camera_total_ = list.total; have_camera_total_ = true;
        // Keep the original live bank-preview behavior, with one outstanding
        // revision-bound change. A release waits for the preceding revision.
        if (bank_release_pending_ && (state.busy || state.playing || !state.paused || state.attach_preview ||
            bank_release_index_<list.first || bank_release_index_>=list.first+list.count ||
            list.rows[bank_release_index_-list.first].time!=bank_anchor_time_))bank_release_pending_=false;
        if (bank_release_pending_ && list.revision != bank_sent_revision_) {
            CameraPose request{};request[0]=list.revision;request[1]=bank_release_value_;
            editor_enqueue(EditorAction::SetCameraRoll,bank_release_index_,&request);
            bank_release_pending_=false;
        }
        TextColored(color(ui::ACCENT), "CAMPATHS");
        SameLine();
        char count[32];
        std::snprintf(count, sizeof(count), "%u PLACED", list.total);
        SetCursorPosX(GetWindowContentRegionMax().x - CalcTextSize(count).x);
        TextDisabled("%s", count);
        if (compact && state.owner == EditorOwner::Panel) {
            if (Button("Tools")) compact_paths_ = false;
            SameLine(); layout_controls();
        }
        Separator();
        const float footer = 4 * GetFrameHeightWithSpacing() + GetStyle().ItemSpacing.y + 1;
        const float row_area = std::max(row_height, GetContentRegionAvail().y - footer - header_height);
        const unsigned rows = std::max(1u, unsigned(row_area / row_height));
        if (camera_pending_first_ != ~0u && (list.revision != camera_pending_revision_ ||
                                            GetTime() - camera_pending_at_ > 2.))
            camera_pending_first_ = ~0u;
        const bool requested_page = camera_pending_first_ == list.first;
        if (requested_page) {
            camera_row_page_ = camera_pending_page_;
            camera_pending_first_ = ~0u;
        } else if (changed_block) camera_pending_first_ = ~0u;
        if (!requested_page && (just_added || changed_block) && state.selected_camera >= list.first &&
            state.selected_camera < list.first + list.count)
            camera_row_page_ = (state.selected_camera - list.first) / rows;
        camera_row_page_ = std::min(camera_row_page_, (std::max(1u, list.count) - 1) / rows);
        // Fill the tail from the preceding rows rather than leaving one camera
        // stranded above an empty sidebar after capture selects the last page.
        const unsigned visible_begin = std::min(camera_row_page_ * rows, list.count > rows ? list.count - rows : 0u);
        const unsigned visible_end = std::min(list.count, visible_begin + rows);
        if (list.count) {
            PushStyleVar(ImGuiStyleVar_CellPadding,ImVec2(2*s,2*s));
            PushStyleColor(ImGuiCol_TableHeaderBg,color(ui::BUTTON));
            const auto row_seed=GetCurrentWindow()->ID;
            PushStyleVar(ImGuiStyleVar_CellPadding,ImVec2(2*s,2*s));
            if (BeginTable("##lite-campath-details",4,ImGuiTableFlags_BordersInnerV |
                           ImGuiTableFlags_RowBg | ImGuiTableFlags_SizingStretchProp)) {
                TableSetupColumn("Camera",ImGuiTableColumnFlags_WidthStretch,camera_width);
                TableSetupColumn("Arrive / s",ImGuiTableColumnFlags_WidthStretch,arrive_width);
                TableSetupColumn("Aspect",ImGuiTableColumnFlags_WidthStretch,aspect_width);
                TableSetupColumn("Bank",ImGuiTableColumnFlags_WidthStretch,bank_width);
                TableHeadersRow();
                for (unsigned i = visible_begin; i < visible_end; ++i) {
                    const unsigned index=list.first+i;
                    const auto& camera=list.rows[i];
                    const bool selected=index==state.selected_camera;
                    TableNextRow(ImGuiTableRowFlags_None,row_height);
                    if(selected)TableSetBgColor(ImGuiTableBgTarget_RowBg0,ImColor(color(ui::SELECTED)));
                    TableSetColumnIndex(0);
                    // Keep camera/field IDs stable when changing their presentation.
                    PushOverrideID(row_seed);PushID(int(index));
                    const auto cell=GetCursorScreenPos();
                    SetNextItemAllowOverlap();
                    const bool clicked=Selectable("##camera",false,ImGuiSelectableFlags_AllowDoubleClick,
                                                   ImVec2(0,row_height-4*s));
                    if(clicked && state.ready && !state.busy && !state.playing)
                        camera_request(IsMouseDoubleClicked(ImGuiMouseButton_Left) ? EditorAction::ViewCamera : EditorAction::SelectCamera,index,list);
                    const float slide=index==animated_camera_ ? 4*s*(1-motion_progress(camera_added_at_,.28)) : 0;
                    SetCursorScreenPos(ImVec2(cell.x+slide,cell.y+2*s));
                    Text("Camera %02u",index+1);
                    if(IsItemHovered() && matching && (info.flags&1))SetTooltip("Replay tick %lld",static_cast<long long>(info.ticks[i]));
                    TableSetColumnIndex(1);
                    BeginDisabled(state.owner != EditorOwner::Panel || !state.ready || !state.paused ||
                                  state.busy || state.playing || state.attach_preview);
                    PushStyleVar(ImGuiStyleVar_FramePadding, ImVec2(2 * s, 2 * s));
                    PushStyleVar(ImGuiStyleVar_FrameBorderSize, 0);
                    PushStyleColor(ImGuiCol_FrameBg, ImVec4(0, 0, 0, 0));
                    PushStyleColor(ImGuiCol_FrameBgHovered, color(ui::FIELD));
                    PushStyleColor(ImGuiCol_FrameBgActive, color(ui::FIELD));
                    SetNextItemWidth(-1);
                    DragFloat("##arrive", &lite_arrive_drafts_[i], .01f, 0.f, 1e9f, "%.2f",
                              ImGuiSliderFlags_AlwaysClamp);
                    if (IsItemActivated())
                        lite_arrive_edit_revisions_[i] = list.revision;
                    lite_arrive_editing_[i] = IsItemActive();
                    const bool arrival_edited = IsItemDeactivatedAfterEdit();
                    if (IsItemHovered())
                        SetTooltip("Camera %02u arrival. Drag to adjust; Ctrl+click to type.",
                                   index + 1);
                    if (arrival_edited) {
                        CameraPose request{};
                        request[0] = lite_arrive_edit_revisions_[i];
                        request[1] = lite_arrive_drafts_[i];
                        request[2] = 1; // Authoritative dispatch snaps to the replay clock.
                        if (!editor_enqueue(EditorAction::SetCameraTime, index, &request))
                            lite_arrive_drafts_[i] = float(camera.time);
                    }
                    PopStyleColor(3);
                    PopStyleVar(2);
                    EndDisabled();
                    TableSetColumnIndex(2);Text("%.2f",camera.aspect);
                    TableSetColumnIndex(3);
                    BeginDisabled(state.owner != EditorOwner::Panel || !state.ready || !state.paused ||
                                  state.busy || state.playing || state.attach_preview);
                    SetNextItemWidth(-1);
                    PushStyleVar(ImGuiStyleVar_FramePadding,ImVec2(2*s,2*s));
                    PushStyleColor(ImGuiCol_FrameBg,ImVec4(0,0,0,0));
                    DragFloat("##bank",&lite_bank_drafts_[i],.25f,-180,180,"%.1f",ImGuiSliderFlags_AlwaysClamp);
                    bool bank_active=IsItemActive(), bank_commit=IsItemDeactivatedAfterEdit();
                    lite_bank_editing_[i]=bank_active;
                    if (IsItemActivated()) {bank_sent_revision_=0;bank_release_pending_=false;bank_anchor_time_=camera.time;}
                    if ((bank_active || bank_commit) && camera.time != bank_anchor_time_) {
                        ClearActiveID();
                        bank_active = bank_commit = false;
                        lite_bank_editing_[i] = false;
                        bank_release_pending_ = false;
                        lite_bank_drafts_[i] = float(camera.roll);
                    }
                    if ((bank_commit || (bank_active && std::abs(lite_bank_drafts_[i]-camera.roll)>.001)) && list.revision != bank_sent_revision_) {
                        CameraPose request{};request[0]=list.revision;request[1]=lite_bank_drafts_[i];
                        if (editor_enqueue(EditorAction::SetCameraRoll,index,&request)) {
                            bank_sent_revision_=list.revision;bank_sent_value_=lite_bank_drafts_[i];
                        } else lite_bank_drafts_[i]=float(camera.roll);
                    } else if (bank_commit && lite_bank_drafts_[i]!=bank_sent_value_) {
                        bank_release_pending_=true;bank_release_index_=index;bank_release_value_=lite_bank_drafts_[i];
                    }
                    if (IsItemHovered())SetTooltip("Camera %02u bank. Drag to rotate; Ctrl+click to type.",index+1);
                    PopStyleColor();PopStyleVar();EndDisabled();
                    PopID();PopID();
                }
                EndTable();
            }
            PopStyleVar();
            PopStyleColor();PopStyleVar();
        } else {
            Spacing(); Spacing();
            TextColored(color(ui::TEXT), "Your first camera starts here");
            TextWrapped("Frame a view, then capture it. Add another view to create a cinematic path.");
            Spacing();
            BeginDisabled(!state.ready || !state.paused || state.busy || state.playing || state.attach_preview);
            action_button("Capture camera", EditorAction::Capture, -1, 0, true);
            EndDisabled();
        }
        SetCursorPosY(GetWindowSize().y - footer - 12 * s);
        BeginDisabled(!state.ready || !state.paused || state.busy || state.playing ||
                      state.attach_preview);
        const unsigned row_first = list.first + visible_begin;
        BeginDisabled(row_first == 0 || camera_pending_first_ != ~0u);
        if (ArrowButton("##previous-cameras", ImGuiDir_Left)) {
            if (camera_row_page_) --camera_row_page_;
            else if (list.first) {
                camera_pending_first_ = ((list.first - 1) / kEditorCameraListCount) * kEditorCameraListCount;
                camera_pending_page_ = (list.first - camera_pending_first_ - 1) / rows;
                camera_pending_revision_ = list.revision;
                camera_pending_at_ = GetTime();
                if (!camera_request(EditorAction::CameraPage, camera_pending_first_, list)) camera_pending_first_ = ~0u;
            }
        }
        EndDisabled(); SameLine();
        if (list.total) TextDisabled("%u-%u of %u", row_first + 1,
                                    std::min({list.total, list.first + list.count, row_first + rows}), list.total);
        else TextDisabled("0 cameras");
        SameLine(GetWindowContentRegionMax().x - GetFrameHeight());
        BeginDisabled(row_first + rows >= list.total || camera_pending_first_ != ~0u);
        if (ArrowButton("##next-cameras", ImGuiDir_Right)) {
            if ((camera_row_page_ + 1) * rows < list.count) ++camera_row_page_;
            else {
                camera_pending_first_ = std::min(((list.first / kEditorCameraListCount) + 1) * kEditorCameraListCount,
                    list.total > kEditorCameraListCount ? list.total - kEditorCameraListCount : 0u);
                camera_pending_page_ = (list.first + list.count - camera_pending_first_) / rows;
                camera_pending_revision_ = list.revision;
                camera_pending_at_ = GetTime();
                if (!camera_request(EditorAction::CameraPage,camera_pending_first_,list)) camera_pending_first_ = ~0u;
            }
        }
        EndDisabled();
        EndDisabled();
        Separator();
        BeginDisabled(!state.ready || !state.paused || state.busy || state.playing || state.attach_preview);
        float history_half = (GetContentRegionAvail().x - 8*s)*.5f;
        BeginDisabled(!(list.flags&1));
        if(Button("Undo",ImVec2(history_half,0)))camera_request(EditorAction::UndoShot,0,list);
        EndDisabled();SameLine();BeginDisabled(!(list.flags&2));
        if(Button("Redo",ImVec2(history_half,0)))camera_request(EditorAction::RedoShot,0,list);
        EndDisabled();
        action_button("Save Path", EditorAction::SaveShot, GetContentRegionAvail().x, 0, true);
        float half = (GetContentRegionAvail().x - 8 * s) * .5f;
        BeginDisabled(state.selected_camera >= list.total);
        if (Button("Delete", ImVec2(half, 0)))
            camera_request(EditorAction::DeleteCamera, state.selected_camera, list);
        EndDisabled();
        SameLine();
        BeginDisabled(!list.total);
        if (Button("Clear All", ImVec2(half, 0))) {
            lite_clear_revision_ = list.revision;
            OpenPopup("Clear cameras?");
        }
        EndDisabled();
        EndDisabled();
        if (BeginPopupModal("Clear cameras?", nullptr, ImGuiWindowFlags_AlwaysAutoResize)) {
            TextUnformatted("Remove every camera from this shot?");
            const bool changed = list.revision != lite_clear_revision_;
            if (changed)
                TextUnformatted("Path changed. Cancel and review it again.");
            const bool can_clear = !changed && state.owner == EditorOwner::Panel && state.ready &&
                                   state.paused && !state.busy && !state.playing && !state.attach_preview;
            BeginDisabled(!can_clear);
            // Keep dispatch bound to the path that opened this confirmation,
            // including programmatic keyboard activation of a disabled item.
            if (Button("Clear") && can_clear && camera_request(EditorAction::ClearCameraPath, 0, list))
                CloseCurrentPopup();
            EndDisabled();
            SameLine();
            if (Button("Cancel"))
                CloseCurrentPopup();
            EndPopup();
        }
        if(layout_editing_ && !full_width) {
            const auto cursor=GetCursorScreenPos(),pos=GetWindowPos();
            SetCursorScreenPos(ImVec2(pos.x+GetWindowSize().x-6*s,pos.y+30*s));
            InvisibleButton("##campath-width",ImVec2(6*s,std::max(20*s,GetWindowSize().y-60*s)));
            if(IsItemHovered() || IsItemActive())SetMouseCursor(ImGuiMouseCursor_ResizeEW);
            if(IsItemHovered())SetTooltip("Drag to adjust sidebar width");
            if(IsItemActivated()) {sidebar_resize_width_=GetWindowSize().x;sidebar_resize_mouse_=io.MousePos;}
            if(IsItemActive())sidebar_width_pending_=std::clamp(sidebar_resize_width_+io.MousePos.x-sidebar_resize_mouse_.x,minimum_width,std::min(360*s,io.DisplaySize.x-32*s));
            if(IsItemDeactivated())save_layout();
            GetWindowDrawList()->AddLine(ImVec2(pos.x+GetWindowSize().x-3*s,pos.y+GetWindowSize().y*.5f-14*s),ImVec2(pos.x+GetWindowSize().x-3*s,pos.y+GetWindowSize().y*.5f+14*s),GetColorU32(ImGuiCol_SliderGrab),s);
            SetCursorScreenPos(cursor);
        }
        End();
        PopStyleVar(5);
    }
}
void OverlayPanel::draw_lite_timeline(const EditorSnapshot& state) {
    using namespace ImGui;
    auto& io = GetIO();
    const float s = panel_scale;
    if (!lite_campaths_visible(state)) return;
    EditorCameraList list{};
    EditorLiteReplayInfo info{};
    EditorReplayEvents events{};
    const bool have_list = editor_camera_list(list) && list.total == state.camera_count;
    const bool have_info = editor_lite_replay_info(info);
    const bool have_events = editor_replay_events(events);
    const bool kills_ready = have_events && events.status == 2;
    const bool replay_ready = state.ready && have_info && (info.flags & 2) && info.total_ticks > 0;
    const unsigned event_status = have_events ? events.status : 0;
    if (replay_ready != lite_replay_ready_seen_ ||
        (event_status != lite_replay_events_status_seen_ && event_status == 2))
        lite_replay_fit_pending_ = true;
    lite_replay_ready_seen_ = replay_ready;
    lite_replay_events_status_seen_ = event_status;
    if (replay_player_filter_ >= 0 && kills_ready) {
        bool found = false;
        for (unsigned i=0;i<events.player_count;++i) found |= events.players[i].id == unsigned(replay_player_filter_);
        if (!found) replay_player_filter_ = -1;
    }
    bool compact = io.DisplaySize.y < 650 * s;
    auto flags = ImGuiWindowFlags_NoTitleBar | ImGuiWindowFlags_NoScrollbar | ImGuiWindowFlags_NoScrollWithMouse;
    if (!layout_editing_) flags |= ImGuiWindowFlags_NoResize | ImGuiWindowFlags_NoMove;
    if (state.owner != EditorOwner::Panel) flags |= ImGuiWindowFlags_NoInputs;
    const float width = std::min(1120 * s, io.DisplaySize.x - 32 * s);
    const float height = lite_timeline_height();
    SetNextWindowPos(outer_position_pending_[1] ? outer_position_[1] : ImVec2((io.DisplaySize.x-width)*.5f,io.DisplaySize.y-height-16*s),
                     (outer_position_pending_[1] || !layout_custom_ || (layout_reset_ & 4)) ? ImGuiCond_Always : ImGuiCond_FirstUseEver);
    outer_position_pending_[1]=false;
    SetNextWindowSize(ImVec2(width,height), (!layout_custom_ || (layout_reset_ & 4)) ? ImGuiCond_Always : ImGuiCond_FirstUseEver);
    layout_reset_ &= ~4u;
    SetNextWindowSizeConstraints(ImVec2(std::min(560 * s, width),height),
                                 ImVec2(io.DisplaySize.x - 32 * s, std::min(260 * s, io.DisplaySize.y - 32 * s)));
    Begin("##lite-timeline",nullptr,flags);
    compact |= GetWindowSize().x < 760 * s;
    constrain_panel(); panel_handle("Drag timeline");
    auto cinematic_button = [&] {
        BeginDisabled(state.camera_count < 2 || !have_list || state.playing || !state.paused || state.attach_preview || cinematic_preparing_);
        PushStyleColor(ImGuiCol_Button, color(ui::ACCENT));
        PushStyleColor(ImGuiCol_Text, color(ui::KEYCAP_INK));
        if (Button("Play cinematic", ImVec2(132 * s, 0))) {
            EditorCinematicStatus previous{};
            if (editor_cinematic_status(previous) && (!cinematic_token_ ||
                std::int32_t(previous.token - cinematic_token_) > 0)) cinematic_token_ = previous.token;
            if (!++cinematic_token_) ++cinematic_token_;
            CameraPose request{}; request[0] = list.revision;
            if (editor_enqueue(EditorAction::PrepareCinematic, cinematic_token_, &request)) {
                cinematic_revision_ = list.revision;
                cinematic_preparing_ = true;
            }
        }
        PopStyleColor(2);
        if (IsItemHovered(ImGuiHoveredFlags_AllowWhenDisabled))
            SetTooltip(state.camera_count < 2 ? "Place at least two cameras to play a cinematic." : "Prepare the replay and play the camera path.");
        EndDisabled();
    };
    auto tick_editor = [&] {
        BeginGroup();
        TextDisabled("Tick"); SameLine();
        if (!lite_tick_editing_) std::snprintf(lite_tick_draft_,sizeof(lite_tick_draft_),"%d",state.tick);
        SetNextItemWidth(90*s);
        BeginDisabled(state.playing || state.attach_preview);
        if (InputText("##lite-tick",lite_tick_draft_,sizeof(lite_tick_draft_),ImGuiInputTextFlags_CharsDecimal |
                      ImGuiInputTextFlags_AutoSelectAll | ImGuiInputTextFlags_EnterReturnsTrue)) {
            char* end=nullptr; const auto tick=std::strtoll(lite_tick_draft_,&end,10);
            const auto total=have_info && (info.flags&2) ? info.total_ticks : -1;
            if(end!=lite_tick_draft_ && !*end && valid_lite_seek_tick(double(tick),total))
                editor_enqueue(EditorAction::SeekReplayTick,double(tick));
        }
        lite_tick_editing_=IsItemActive();
        if(IsItemHovered())SetTooltip("Type a replay tick and press Enter to seek.");
        EndDisabled();SameLine();
        if(have_info && (info.flags&2))TextDisabled("/ %lld",static_cast<long long>(info.total_ticks));
        else TextDisabled("/ --");
        EndGroup();
    };
    auto player_filter = [&] {
        if (replay_player_filter_ < 0 && kills_ready)
            for (unsigned i=0;i<events.player_count;++i) if (events.players[i].id) {replay_player_filter_=int(events.players[i].id);break;}
        auto focus = [&] {
            if (state.ready && !state.busy && state.paused && !state.playing && !state.attach_preview)
                editor_enqueue(EditorAction::FocusReplayPlayer, replay_player_filter_);
        };
        auto change = [&](bool forward) {
            int ids[kReplayPlayers]{}; unsigned count=0,current=0;
            for (unsigned i=0;i<events.player_count;++i) if (events.players[i].id) {
                ids[count]=int(events.players[i].id); if(ids[count]==replay_player_filter_)current=count; ++count;
            }
            if (count) { replay_player_filter_=ids[forward ? (current+1)%count : (current+count-1)%count]; focus(); }
        };
        BeginDisabled(!kills_ready || !events.player_count || state.playing || state.attach_preview);
        PushStyleVar(ImGuiStyleVar_FramePadding, ImVec2(3*s,3*s));
        PushStyleVar(ImGuiStyleVar_FrameBorderSize,0);
        PushStyleColor(ImGuiCol_Button,ImVec4(0,0,0,0));
        if (ArrowButton("##previous-player",ImGuiDir_Left)) change(false);
        SameLine(0,4*s);
        const char* name = kills_ready && replay_player_filter_>=0 ? replay_player_name(events,replay_player_filter_) : "Players";
        const auto text_size=CalcTextSize(name);
        const float name_width=(compact ? 128.f : 176.f)*s;
        const auto pos=GetCursorScreenPos();
        if (InvisibleButton("##player-name",ImVec2(name_width,GetFrameHeight()))) focus();
        const ImVec2 text_pos(pos.x+std::max(0.f,(name_width-text_size.x)*.5f),pos.y+GetStyle().FramePadding.y);
        RenderTextEllipsis(GetWindowDrawList(),text_pos,ImVec2(pos.x+name_width,pos.y+GetFrameHeight()),
                           pos.x+name_width,pos.x+name_width,name,nullptr,&text_size);
        if (IsItemHovered(ImGuiHoveredFlags_AllowWhenDisabled)) {
            const char* camera_hint = state.ready ? "Click the name or arrows to move freecam near this player." : "Camera selection is unavailable at this tick.";
            if (kills_ready && replay_player_filter_ >= 0) {
                unsigned kills = 0, deaths = 0;
                for (unsigned i = 0; i < events.count; ++i) {
                    const auto kind = replay_event_kind(events.kills[i],replay_player_filter_);
                    kills += kind == ReplayEventKind::Kill;
                    deaths += kind == ReplayEventKind::Death;
                }
                SetTooltip("%s\n%u kills | %u deaths (full replay)\nBlue: kills. Red: deaths.\n%s",name,kills,deaths,camera_hint);
            } else
                SetTooltip("%s\n%s",have_events ? events.message : "Reading replay kills...",camera_hint);
        }
        SameLine(0,4*s);
        if (ArrowButton("##next-player",ImGuiDir_Right)) change(true);
        PopStyleColor(); PopStyleVar(2); EndDisabled();
    };
    BeginDisabled(!state.ready || state.busy);
    PushStyleColor(ImGuiCol_Button,color(ui::SELECTED));
    if (Button(lite_campath_timeline_ ? "Campaths###lite-timeline-mode" : "Replay###lite-timeline-mode",ImVec2(90*s,0))) {
        lite_campath_timeline_ = !lite_campath_timeline_;
        lite_replay_dragging_ = false;
    }
    PopStyleColor();
    if (IsItemHovered()) SetTooltip("Switch timeline. Wheel to zoom; right-drag to pan. Alt+drag a camera to change its arrival tick.");
    SameLine();cinematic_button();
    const float player_width = (compact ? 128.f : 176.f)*s + 2*(GetFontSize()+6*s) + 8*s;
    if (compact) SameLine();
    else SameLine(std::max(GetCursorPosX(), (GetWindowSize().x-player_width)*.5f));
    player_filter();
    if (compact) {
        SameLine();
        if (Button("More")) OpenPopup("##compact-transport");
    } else {
        SameLine(GetWindowContentRegionMax().x - 185 * s);
        TextDisabled("Kills   |   Wheel: zoom");
    }
    char total_label[32];
    if(have_info && (info.flags&2))std::snprintf(total_label,sizeof(total_label),"/ %lld",static_cast<long long>(info.total_ticks));
    else std::snprintf(total_label,sizeof(total_label),"/ --");
    const float tick_width=CalcTextSize("Tick").x+90*s+CalcTextSize(total_label).x+2*GetStyle().ItemSpacing.x;
    const float tick_x=GetWindowContentRegionMax().x-tick_width;
    const float tick_screen_x=GetWindowPos().x+tick_x;
    const float track_width = std::max(80 * s, GetContentRegionAvail().x);
    const auto tick_seed=GetCurrentWindow()->ID;
    PushStyleVar(ImGuiStyleVar_WindowPadding,ImVec2(0,0));
    BeginChild("##lite-shot-track",ImVec2(compact ? std::max(80*s,track_width-tick_width-8*s) : 0,
               (compact ? 42.f : 70.f)*s),ImGuiChildFlags_None,
               ImGuiWindowFlags_NoBackground | ImGuiWindowFlags_NoScrollbar | ImGuiWindowFlags_NoScrollWithMouse);
    BeginDisabled(state.playing || state.attach_preview ||
                  (lite_campath_timeline_ ? !state.camera_count : !(have_info && (info.flags&2) && info.total_ticks>0)));
    SetCursorPosY(GetCursorPosY() + (compact ? 20.f : 26.f) * s);
    SliderRow track{};
    if (lite_campath_timeline_) {
        if (!IsAnyItemActive() && (lite_shot_playhead_ != state.playhead || lite_shot_duration_ != state.duration ||
            (have_list && lite_shot_revision_ != list.revision))) {
            lite_shot_time_ = float(std::clamp(state.playhead,0.,state.duration));
            lite_shot_playhead_ = state.playhead;
            lite_shot_duration_ = state.duration;
            lite_shot_revision_ = have_list ? list.revision : 0;
        }
        const auto guides = visualization_snapshot();
        track = slider_row("##lite-shot-position","Shot",&lite_shot_time_,0,
                           float(std::max(state.duration,.001)),"%.3f s",42,guides.get(),true);
        lite_shot_time_ = std::clamp(lite_shot_time_,0.f,float(state.duration));
    } else {
        const auto known_total=have_info && (info.flags&2) ? info.total_ticks : -1;
        if(known_total!=lite_replay_total_seen_ || (replay_ready && lite_replay_fit_pending_)) {
            timeline_view_id_=nullptr;
            lite_replay_total_seen_=known_total;
            if (replay_ready) lite_replay_fit_pending_ = false;
        }
        if (!lite_replay_dragging_) lite_replay_cursor_ = state.tick;
        float cursor = float(lite_replay_cursor_);
        track = slider_row("##lite-replay-position","Tick",&cursor,0,
                           float(have_info ? std::max<std::int64_t>(1,info.total_ticks-1) : 1),nullptr,42,nullptr,true);
        lite_replay_cursor_ = std::int64_t(std::nearbyint(cursor));
        lite_replay_dragging_ = track.active;
    }
    // Replay kills use the same visible track as camera keyframes. Hovering a
    // dense group lists the selected player's kills/deaths; a click seeks one tick.
    int hovered_kill = -1;
    float closest = 8*s;
    const auto mouse = io.MousePos;
    const float span = timeline_view_end_ - timeline_view_start_;
    if (kills_ready && span>0 && (!lite_campath_timeline_ || (have_info && (info.flags&1)))) {
        auto* draw = GetWindowDrawList();
        int last_label_tick = -1;
        for (unsigned i=0;i<events.count;++i) {
            const auto& kill = events.kills[i];
            const auto kind = replay_event_kind(kill,replay_player_filter_);
            if (kind == ReplayEventKind::Hidden) continue;
            const double time = lite_campath_timeline_ ? double(kill.tick-info.start_tick)/info.tick_rate : kill.tick;
            if (time < timeline_view_start_ || time > timeline_view_end_) continue;
            const float x = timeline_x0_ + (timeline_x1_-timeline_x0_)*float((time-timeline_view_start_)/span);
            const auto tint = color(kind == ReplayEventKind::Kill ? 0x65b5ff : 0xff727a);
            // Markers have a separate lane and an outlined stem, so the
            // playhead at the same tick cannot cover the event.
            draw->AddLine(ImVec2(x,timeline_y_-18*s),ImVec2(x,timeline_y_-7*s),IM_COL32(12,16,19,255),5*s);
            draw->AddLine(ImVec2(x,timeline_y_-18*s),ImVec2(x,timeline_y_-7*s),ImColor(tint),3*s);
            if (!compact && span <= 512 && (last_label_tick < 0 || kill.tick - last_label_tick >= span * 70*s/std::max(1.f,timeline_x1_-timeline_x0_))) {
                char tick_label[24]; std::snprintf(tick_label,sizeof(tick_label),"T %d",kill.tick);
                const float tw = CalcTextSize(tick_label).x;
                draw->AddText(ImVec2(std::clamp(x-tw*.5f,timeline_x0_,std::max(timeline_x0_,timeline_x1_-tw)),timeline_y_-39*s),ImColor(tint),tick_label);
                last_label_tick = kill.tick;
            }
            if (state.owner==EditorOwner::Panel && state.ready && !state.busy &&
                // The slider may acquire the click first; a marker then
                // deliberately replaces that gesture. Popups still block it.
                IsWindowHovered(ImGuiHoveredFlags_RootAndChildWindows |
                                ImGuiHoveredFlags_AllowWhenBlockedByActiveItem) &&
                !(GetCurrentContext()->CurrentItemFlags & ImGuiItemFlags_Disabled) &&
                mouse.y>=timeline_y_-28*s && mouse.y<=timeline_y_-7*s && std::abs(mouse.x-x)<=closest) {
                closest=std::abs(mouse.x-x); hovered_kill=int(i);
            }
        }
        if (hovered_kill>=0 && !state.playing && !state.attach_preview) {
            const auto& kill=events.kills[hovered_kill];
            SetMouseCursor(ImGuiMouseCursor_Hand);
            BeginTooltip();
            for (unsigned i=0;i<events.count;++i) {
                const auto& nearby=events.kills[i];
                if (!kill_matches(nearby,replay_player_filter_)) continue;
                const double time = lite_campath_timeline_ ? double(nearby.tick-info.start_tick)/info.tick_rate : nearby.tick;
                const float x=timeline_x0_+(timeline_x1_-timeline_x0_)*float((time-timeline_view_start_)/span);
                if (std::abs(mouse.x-x)<=8*s)
                    Text("T %d  %s killed %s",nearby.tick,replay_player_name(events,nearby.killer),replay_player_name(events,nearby.victim));
            }
            TextDisabled("Blue: kills. Red: deaths. Click to seek; zoom to separate markers.");
            EndTooltip();
            if (IsMouseClicked(ImGuiMouseButton_Left)) {
                // Replace the slider gesture completely. Otherwise its edited
                // deactivation emits a second scrub seek on the next frame.
                GetCurrentContext()->ActiveIdHasBeenEditedBefore = false;
                GetCurrentContext()->ActiveIdHasBeenEditedThisFrame = false;
                ClearActiveID(); lite_replay_dragging_=false; track.committed=false;
                editor_enqueue(EditorAction::SeekReplayTick,double(kill.tick));
            }
        }
    }
    if (!lite_campath_timeline_ && track.committed && valid_lite_seek_tick(double(lite_replay_cursor_),info.total_ticks))
        editor_enqueue(EditorAction::SeekReplayTick,double(lite_replay_cursor_));
    EndDisabled();
    // A quiet ruler makes the visible zoom range explicit in both modes.
    if (!compact && span > 0) {
        auto* draw = GetWindowDrawList();
        const unsigned divisions = timeline_x1_ - timeline_x0_ > 420 * s ? 4 : 2;
        for (unsigned i = 0; i <= divisions; ++i) {
            const float fraction = float(i) / divisions;
            const double value = timeline_view_start_ + span * fraction;
            const float x = timeline_x0_ + (timeline_x1_ - timeline_x0_) * fraction;
            char label[32];
            std::snprintf(label, sizeof(label), lite_campath_timeline_ ? "%.2f s" : "%.0f", value);
            const float text_width = CalcTextSize(label).x;
            const float label_x = std::clamp(x - text_width * .5f, timeline_x0_,
                                            std::max(timeline_x0_, timeline_x1_ - text_width));
            if(i<divisions && label_x+text_width<tick_screen_x-8*s)
                draw->AddText(ImVec2(label_x, timeline_y_ + 10 * s), GetColorU32(ImGuiCol_TextDisabled), label);
        }
    }
    if (!compact) {
        // Share the ruler's window so it cannot intercept mouse input meant for
        // the tick field. Preserve the existing ID while changing ownership.
        SetCursorScreenPos(ImVec2(tick_screen_x,timeline_y_+6*s));
        PushOverrideID(tick_seed);tick_editor();PopID();
    }
    EndChild(); PopStyleVar();
    auto after_track=GetCursorScreenPos();
    if (compact) {
        SetCursorScreenPos(ImVec2(tick_screen_x,timeline_y_-GetFrameHeight()*.5f));
        tick_editor();
    } else after_track.y-=6*s; // Keep the transport spacing below the taller ruler.
    SetCursorScreenPos(after_track);
    const bool compact_popup = compact && BeginPopup("##compact-transport");
    if (!compact || compact_popup) {
    if(!compact)SetCursorPosX(GetWindowSize().x*.5f-38*s-GetStyle().ItemSpacing.x-100*s);
    BeginGroup();
    BeginDisabled(!state.paused || state.playing || state.attach_preview || !state.camera_count);
    action_button("< Previous", EditorAction::PreviousView, 100*s);
    if (IsItemHovered()) SetTooltip("Select and view the previous saved camera.");
    EndDisabled(); SameLine();
    BeginDisabled(state.playing || state.attach_preview ||
                  (lite_campath_timeline_ ? !state.camera_count : !(have_info && (info.flags&2))));
    action_button("Seek here",lite_campath_timeline_ ? EditorAction::SeekShot : EditorAction::SeekReplayTick,
                  76*s,lite_campath_timeline_ ? double(lite_shot_time_) : double(lite_replay_cursor_));
    if (IsItemHovered()) SetTooltip(lite_campath_timeline_ ? "Apply the selected point on the campath shot." : "Seek to the selected replay tick.");
    EndDisabled(); SameLine();
    BeginDisabled(!state.paused || state.playing || state.attach_preview || !state.camera_count);
    action_button("Forward >", EditorAction::NextView, 100*s);
    if (IsItemHovered()) SetTooltip("Select and view the next saved camera.");
    EndDisabled();
    EndGroup();
    if (!compact) transport_width_ = GetItemRectSize().x;
    if (!compact) SetCursorPosX(std::max(GetStyle().WindowPadding.x, (GetWindowSize().x-speed_width_)*.5f));
    BeginGroup();
    action_button(state.paused ? "Resume" : "Pause",EditorAction::PlayPause,83*s);
    SameLine();
    // Match the desktop's acknowledged preference without flashing the previous
    // value back while the configuration makes its normal round trip.
    const auto now_ms = GetTickCount64();
    if (state.pause_after_capture == pause_capture_pending_value_ ||
        now_ms >= pause_capture_pending_until_)
        pause_capture_pending_until_ = 0;
    bool pause_after_capture = pause_capture_pending_until_ ? pause_capture_pending_value_ :
                                                           state.pause_after_capture;
    if (Checkbox("Pause after capture", &pause_after_capture) &&
        editor_enqueue(EditorAction::SetPauseAfterCapture, pause_after_capture ? 1 : 0)) {
        pause_capture_pending_value_ = pause_after_capture;
        pause_capture_pending_until_ = now_ms + 1000;
    }
    if (IsItemHovered(ImGuiHoveredFlags_AllowWhenDisabled))
        SetTooltip("Pause the replay after capturing a camera. Also applies to the capture shortcut.");
    // Compact transport lives in a popup. Keep its preference row distinct so
    // the popup still fits smaller viewports with every speed and FOV control.
    if (!compact_popup) SameLine();
    TextDisabled("Speed");SameLine();
    for(double value : {.25,.5,1.,2.,4.}) {
        char label[16];std::snprintf(label,sizeof(label),"%gx",value);
        const bool selected=std::abs(state.playback_speed-value)<.0001;
        if(selected) {PushStyleColor(ImGuiCol_Button,color(ui::SELECTED_BLUE));PushStyleColor(ImGuiCol_Text,color(ui::STRONG));}
        if(Button(label))editor_enqueue(EditorAction::SetPlaybackSpeed,value);
        if(selected)PopStyleColor(2);SameLine();
    }
    if (GetContentRegionAvail().x < 120 * s) NewLine();
    TextDisabled("FOV");SameLine();SetNextItemWidth(74*s);
    BeginDisabled(!state.paused || state.playing || state.attach_preview || !state.manual_active || state.horizontal_fov<=0);
    if(!lite_fov_editing_)lite_fov_draft_=float(state.horizontal_fov);
    InputFloat("##lite-fov",&lite_fov_draft_,0,0,"%.1f",ImGuiInputTextFlags_AutoSelectAll);
    const bool fov_commit=IsItemDeactivatedAfterEdit();lite_fov_editing_=IsItemActive();
    if(fov_commit) {const auto factor=lite_fov_factor(state.horizontal_fov,lite_fov_draft_);if(std::isfinite(factor))editor_request_framing_factor(factor);}
    EndDisabled();
    EndGroup();
    if (!compact) speed_width_ = GetItemRectSize().x;
    }
    if (compact_popup) EndPopup();
    EndDisabled();
    EditorCinematicStatus preparation{};
    const bool have_preparation = editor_cinematic_status(preparation) &&
        preparation.token == cinematic_token_ && preparation.revision == cinematic_revision_;
    const bool canceled_preparation = have_preparation && preparation.state == 3;
    if (canceled_preparation) cinematic_preparing_ = false;
    if (cinematic_preparing_) {
        if (!have_list || list.revision != cinematic_revision_ || IsKeyPressed(ImGuiKey_Escape, false))
            cinematic_preparing_ = false;
        else if (have_preparation) {
            if (preparation.state == 3) cinematic_preparing_ = false;
            else if (preparation.state == 2 && state.ready && !state.busy && state.paused &&
                     !state.playing && !state.attach_preview && state.camera_count >= 2 &&
                     editor_enqueue(EditorAction::PlayPath,0)) {
                cinematic_preparing_ = false;
            }
        }
    }
    End();
}
}

// Layout preferences belong to presentation, never to the camera project or IPC.
#include "dolly_overlay_panel.hpp"
#include "imgui_internal.h"
#include <algorithm>
#include <cstdio>
#include <cstring>
#include <cfloat>
#include <cmath>
#include <windows.h>

namespace dolly {
float OverlayPanel::lite_timeline_height() const {
    return (ImGui::GetIO().DisplaySize.y < 650 * panel_scale ? 100.f : 180.f) * panel_scale;
}
float OverlayPanel::motion_progress(double started, double duration) const {
    if (reduced_motion_) return 1;
    const float t = float(std::clamp((ImGui::GetTime() - started) / duration, 0., 1.));
    return 1 - (1 - t) * (1 - t) * (1 - t);
}
void* OverlayPanel::read_layout_open(ImGuiContext*, ImGuiSettingsHandler* handler, const char*) {
    return handler->UserData;
}
void OverlayPanel::read_layout_line(ImGuiContext*, ImGuiSettingsHandler*, void* entry, const char* line) {
    auto& panel = *static_cast<OverlayPanel*>(entry);
    int value = 0;
    if (std::sscanf(line, "ReducedMotion=%d", &value) == 1) panel.reduced_motion_ = value != 0;
    if (std::sscanf(line, "Classic=%d", &value) == 1) panel.classic_layout_ = value != 0;
    if (std::sscanf(line, "Custom=%d", &value) == 1) panel.layout_custom_ = value != 0;
    if (std::sscanf(line, "EditorCustom=%d", &value) == 1) panel.editor_custom_ = value != 0;
    if (std::sscanf(line, "SidebarWidthCurrent=%d", &value) == 1) panel.sidebar_width_current_ = value != 0;
    int p=-1,c[4]{};float w[3]{},h[4]{};
    if(std::sscanf(line,"Columns%d=%d,%d,%d,%d",&p,&c[0],&c[1],&c[2],&c[3])==5 && p>=0 && p<5 &&
       std::all_of(std::begin(c),std::end(c),[](int x){return x>=-1 && x<3;}))
        std::copy(std::begin(c),std::end(c),panel.section_column_pref_[p]);
    if(std::sscanf(line,"Widths%d=%f,%f,%f",&p,&w[0],&w[1],&w[2])==4 && p>=0 && p<5 &&
       std::all_of(std::begin(w),std::end(w),[](float x){return std::isfinite(x) && x>=.2f && x<=3;}))
        std::copy(std::begin(w),std::end(w),panel.column_weights_[p]);
    if(std::sscanf(line,"Heights%d=%f,%f,%f,%f",&p,&h[0],&h[1],&h[2],&h[3])==5 && p>=0 && p<5 &&
       std::all_of(std::begin(h),std::end(h),[](float x){return std::isfinite(x) && x>=0 && x<=900;}))
        std::copy(std::begin(h),std::end(h),panel.section_minimum_[p]);
    int page=-1, consumed=0; unsigned slots[4]{};
    if (std::sscanf(line,"Sections%d=%u,%u,%u,%u%n",&page,&slots[0],&slots[1],&slots[2],&slots[3],&consumed)==5 &&
        page>=0 && page<5 && (line[consumed]==0 || (line[consumed]=='\r' && line[consumed+1]==0))) {
        bool seen[4]{}; bool valid=true;
        const auto count=section_count(page);
        for(unsigned i=0;i<4;++i) {
            if(slots[i]>=4 || seen[slots[i]] || (i<count ? slots[i]>=count : slots[i]!=i)) {valid=false;break;}
            seen[slots[i]]=true;
        }
        if(valid)std::copy(std::begin(slots),std::end(slots),panel.section_slots_[page]);
    }
}
void OverlayPanel::write_layout(ImGuiContext*, ImGuiSettingsHandler* handler, ImGuiTextBuffer* out) {
    const auto& panel = *static_cast<OverlayPanel*>(handler->UserData);
    out->appendf("[DollyUI][Preferences]\nReducedMotion=%d\nClassic=%d\nCustom=%d\nEditorCustom=%d\n",
                 int(panel.reduced_motion_), int(panel.classic_layout_), int(panel.layout_custom_),int(panel.editor_custom_));
    for(int page=0;page<5;++page)out->appendf("Sections%d=%u,%u,%u,%u\n",page,
        panel.section_slots_[page][0],panel.section_slots_[page][1],panel.section_slots_[page][2],panel.section_slots_[page][3]);
    for(int page=0;page<5;++page) {
        out->appendf("Columns%d=%d,%d,%d,%d\n",page,panel.section_column_pref_[page][0],panel.section_column_pref_[page][1],panel.section_column_pref_[page][2],panel.section_column_pref_[page][3]);
        out->appendf("Widths%d=%.4f,%.4f,%.4f\n",page,panel.column_weights_[page][0],panel.column_weights_[page][1],panel.column_weights_[page][2]);
        out->appendf("Heights%d=%.2f,%.2f,%.2f,%.2f\n",page,panel.section_minimum_[page][0],panel.section_minimum_[page][1],panel.section_minimum_[page][2],panel.section_minimum_[page][3]);
    }
    out->appendf("SidebarWidthCurrent=%d\n\n",int(panel.sidebar_width_current_));
}
void OverlayPanel::initialize_layout() {
    auto& io = ImGui::GetIO();
    ImGuiSettingsHandler handler{};
    handler.TypeName = "DollyUI";
    handler.TypeHash = ImHashStr(handler.TypeName);
    handler.UserData = this;
    handler.ReadOpenFn = read_layout_open;
    handler.ReadLineFn = read_layout_line;
    handler.WriteAllFn = write_layout;
    ImGui::AddSettingsHandler(&handler);
    const auto override_length = GetEnvironmentVariableA("DOLLY_UI_LAYOUT_FILE", layout_file_, sizeof(layout_file_));
    if (override_length && override_length < sizeof(layout_file_)) {
        io.IniFilename = std::strcmp(layout_file_, "none") ? layout_file_ : nullptr;
        return;
    }
    char directory[400]{};
    const auto length = GetEnvironmentVariableA("LOCALAPPDATA", directory, sizeof(directory));
    if (length && length < sizeof(directory) - 20) {
        std::strcat(directory, "\\DeadlockDolly");
        CreateDirectoryA(directory, nullptr);
        std::snprintf(layout_file_, sizeof(layout_file_), "%s\\ui-layout.ini", directory);
        io.IniFilename = layout_file_;
        io.IniSavingRate = .5f;
    }
}
void OverlayPanel::constrain_panel() {
    using namespace ImGui;
    if (IsMouseDown(ImGuiMouseButton_Left)) return;
    const auto display = GetIO().DisplaySize;
    const auto size = GetWindowSize();
    const auto pos = GetWindowPos();
    const float margin = 12 * panel_scale;
    const ImVec2 bounded(std::clamp(pos.x, margin, std::max(margin, display.x - size.x - margin)),
                         std::clamp(pos.y, margin, std::max(margin, display.y - size.y - margin)));
    if (bounded.x != pos.x || bounded.y != pos.y) SetWindowPos(bounded);
}
void OverlayPanel::panel_handle(const char* label, bool editor) {
    using namespace ImGui;
    const bool campaths = !std::strcmp(label,"Drag campaths");
    if (!editor && !campaths && !layout_editing_) return;
    const auto cursor = GetCursorScreenPos();
    const auto position = GetWindowPos();
    float width = GetWindowSize().x - 2 * GetStyle().WindowPadding.x;
    if(editor && (GetIO().DisplaySize.x<900*panel_scale || GetIO().DisplaySize.y<650*panel_scale))
        width-=62*panel_scale+GetStyle().ItemSpacing.x;
    SetCursorScreenPos(ImVec2(position.x + GetStyle().WindowPadding.x, position.y + 3 * panel_scale));
    InvisibleButton("##panel-handle", ImVec2(width, (editor || campaths) ? GetFrameHeight()+3*panel_scale : 8 * panel_scale));
    const float middle = position.x + GetWindowSize().x * .5f;
    GetWindowDrawList()->AddRectFilled(ImVec2(middle-22*panel_scale,position.y+5*panel_scale),
                                       ImVec2(middle+22*panel_scale,position.y+7*panel_scale),
                                       GetColorU32(ImGuiCol_SliderGrab),panel_scale);
    if (IsItemHovered() || IsItemActive()) SetMouseCursor(ImGuiMouseCursor_ResizeAll);
    if (IsItemHovered()) SetTooltip("%s",label);
    const unsigned which=editor ? 0 : campaths ? 1 : 2;
    if(IsItemActivated()) {drag_start_[which]=position;drag_mouse_[which]=GetIO().MousePos;}
    if (IsItemActive() && IsMouseDragging(ImGuiMouseButton_Left)) {
        const auto pos = GetWindowPos();
        if (editor) {
            editor_custom_=true;editor_dragging_=true;editor_position_pending_=true;
            const auto display=GetIO().DisplaySize;
            const float margin=12*panel_scale;
            editor_position_=ImVec2(std::clamp(drag_start_[which].x+GetIO().MousePos.x-drag_mouse_[which].x,margin,std::max(margin,display.x-GetWindowSize().x-margin)),
                                    std::clamp(drag_start_[which].y+GetIO().MousePos.y-drag_mouse_[which].y,margin,std::max(margin,display.y-GetWindowSize().y-margin)));
            MarkIniSettingsDirty();
        } else {
            outer_position_[which-1]=ImVec2(drag_start_[which].x+GetIO().MousePos.x-drag_mouse_[which].x,
                                           drag_start_[which].y+GetIO().MousePos.y-drag_mouse_[which].y);
            if (campaths) {
                // Like the main header, moving this panel needs no Arrange
                // mode. Keep its normal controls and resize lock untouched.
                layout_custom_=true;
                const auto display=GetIO().DisplaySize;
                const float margin=12*panel_scale;
                outer_position_[0].x=std::clamp(outer_position_[0].x,margin,std::max(margin,display.x-GetWindowSize().x-margin));
                outer_position_[0].y=std::clamp(outer_position_[0].y,margin,std::max(margin,display.y-GetWindowSize().y-margin));
                MarkIniSettingsDirty();
            }
            outer_position_pending_[which-1]=true;
        }
    }
    if(editor && IsItemDeactivated() && editor_dragging_) {editor_dragging_=false;save_layout();}
    if(!editor && IsItemDeactivated())save_layout();
    SetCursorScreenPos(cursor);
}
unsigned OverlayPanel::section_count(int page) { return page>=3 ? 4u : 2u; }
void OverlayPanel::save_layout() {
    ImGui::MarkIniSettingsDirty();
    if(ImGui::GetIO().IniFilename)ImGui::SaveIniSettingsToDisk(ImGui::GetIO().IniFilename);
}
void OverlayPanel::prepare_sections() {
    const auto count=section_count(lite_page_);
    const float gap=12*panel_scale;
    const float available=ImGui::GetContentRegionAvail().x;
    const float capacity=ImGui::GetContentRegionAvail().y;
    section_canvas_=ImVec2(available,capacity);
    const float total=available-gap*(layout_columns_-1);
    float weight=0;for(unsigned c=0;c<layout_columns_;++c)weight+=column_weights_[lite_page_][c];
    const float minimum=std::min(total/layout_columns_,(layout_columns_==3 ? 160.f : 240.f)*panel_scale);
    const float flexible=std::max(0.f,total-minimum*layout_columns_);
    float x=ImGui::GetWindowContentRegionMin().x;
    for(unsigned c=0;c<layout_columns_;++c) {
        column_x_[c]=x;
        column_widths_[c]=c+1==layout_columns_ ? available-(x-ImGui::GetWindowContentRegionMin().x) :
            std::floor(minimum+flexible*column_weights_[lite_page_][c]/weight+.5f);
        x+=column_widths_[c]+gap;
    }
    auto preferred=[&](unsigned slot) {
        if(lite_page_==3 && layout_columns_>1) {
            static constexpr unsigned two[]={0,1,1,0},three[]={0,1,2,2};
            return layout_columns_==2 ? two[slot] : three[slot];
        }
        return slot%layout_columns_;
    };
    auto desired=[&](unsigned index) {return section_column_pref_[lite_page_][index]>=0 ?
        std::min(unsigned(section_column_pref_[lite_page_][index]),layout_columns_-1) : preferred(section_slots_[lite_page_][index]);};
    unsigned best[4]{}, combinations=1; bool custom=false;
    for(unsigned i=0;i<count;++i) {combinations*=layout_columns_;custom|=section_slots_[lite_page_][i]!=i || section_column_pref_[lite_page_][i]>=0;best[i]=desired(i);}
    if(custom) {
        float best_score=FLT_MAX;
        for(unsigned assignment=0;assignment<combinations;++assignment) {
            unsigned candidate[4]{},encoded=assignment;float heights[3]{},score=0;
            for(unsigned i=0;i<count;++i) {
                candidate[i]=encoded%layout_columns_;encoded/=layout_columns_;
                const float h=section_heights_[lite_page_][i]*panel_scale;
                if(heights[candidate[i]])heights[candidate[i]]+=gap;
                heights[candidate[i]]+=h;
                if(candidate[i]!=desired(i))score+=h;
            }
            for(unsigned col=0;col<layout_columns_;++col)score+=std::max(0.f,heights[col]-capacity)*10000;
            if(score<best_score) {best_score=score;std::copy(std::begin(candidate),std::end(candidate),best);}
        }
    }
    float ys[3]{};
    float natural[3]{},extra[3]{};unsigned numbers[3]{};
    for(unsigned i=0;i<count;++i) {natural[best[i]]+=section_heights_[lite_page_][i]*panel_scale;extra[best[i]]+=std::max(0.f,section_minimum_[lite_page_][i]-section_heights_[lite_page_][i])*panel_scale;++numbers[best[i]];}
    for(unsigned c=0;c<layout_columns_;++c)if(numbers[c])natural[c]+=gap*(numbers[c]-1);
    for(unsigned slot=0;slot<count;++slot) for(unsigned index=0;index<count;++index) if(section_slots_[lite_page_][index]==slot) {
        const auto column=best[index];section_columns_[index]=column;
        section_widths_[index]=column_widths_[column];
        section_extra_draw_[index]=std::max(0.f,section_minimum_[lite_page_][index]-section_heights_[lite_page_][index])*panel_scale*
            (extra[column]>0 ? std::min(1.f,std::max(0.f,capacity-natural[column])/extra[column]) : 1);
        section_positions_[index]=ImVec2(column_x_[column],card_origin_y_+ys[column]);
        ys[column]+=section_heights_[lite_page_][index]*panel_scale+section_extra_draw_[index]+gap;
    }
}
void OverlayPanel::finish_section_layout() {
    using namespace ImGui;
    const auto* payload=GetDragDropPayload();
    if(!layout_editing_ || !payload || !payload->IsDataType("DOLLY_SECTION") || payload->DataSize!=sizeof(SectionPayload)) {section_ghost_active_=false;return;}
    const auto source=*static_cast<const SectionPayload*>(payload->Data);
    if(source.page!=lite_page_ || source.index>=section_count(lite_page_))return;
    const auto mouse=GetIO().MousePos, origin=GetWindowPos();
    const ImVec2 target(mouse.x-24*panel_scale,mouse.y-14*panel_scale);
    if(!section_ghost_active_) {section_ghost_=ImVec2(origin.x+section_positions_[source.index].x,origin.y+section_positions_[source.index].y);section_ghost_active_=true;}
    const float blend=reduced_motion_ ? 1.f : std::min(1.f,GetIO().DeltaTime*24);
    section_ghost_.x+=(target.x-section_ghost_.x)*blend;section_ghost_.y+=(target.y-section_ghost_.y)*blend;
    const ImVec2 size(section_widths_[source.index],section_heights_[lite_page_][source.index]*panel_scale+section_extra_draw_[source.index]);
    auto* foreground=GetForegroundDrawList();
    const ImVec2 end(section_ghost_.x+size.x,section_ghost_.y+size.y);
    foreground->AddRectFilled(ImVec2(section_ghost_.x+5*panel_scale,section_ghost_.y+7*panel_scale),ImVec2(end.x+5*panel_scale,end.y+7*panel_scale),IM_COL32(0,0,0,100),6*panel_scale);
    foreground->AddRectFilled(section_ghost_,end,IM_COL32(31,45,48,215),6*panel_scale);
    foreground->AddRect(section_ghost_,end,GetColorU32(ImGuiCol_SliderGrab),6*panel_scale,0,1.5f*panel_scale);
    foreground->AddText(ImVec2(section_ghost_.x+12*panel_scale,section_ghost_.y+10*panel_scale),GetColorU32(ImGuiCol_Text),section_names_[source.index]);
    foreground->AddText(ImVec2(section_ghost_.x+12*panel_scale,section_ghost_.y+35*panel_scale),IM_COL32(150,175,171,210),"Drop to place section");
    // Empty canvas is a real destination, not merely another swap target.
    bool occupied=false;
    for(unsigned i=0;i<section_count(lite_page_);++i) {
        const ImVec2 pos(origin.x+section_positions_[i].x,origin.y+section_positions_[i].y);
        occupied|=ImRect(pos,ImVec2(pos.x+section_widths_[i],pos.y+section_heights_[lite_page_][i]*panel_scale+section_extra_draw_[i])).Contains(mouse);
    }
    if(occupied)return;
    const ImRect canvas(ImVec2(origin.x+GetWindowContentRegionMin().x,origin.y+card_origin_y_),
                        ImVec2(origin.x+GetWindowContentRegionMin().x+section_canvas_.x,origin.y+card_origin_y_+section_canvas_.y));
    if(!BeginDragDropTargetCustom(canvas,GetID("##empty-section-space")))return;
    if(const auto* accepted=AcceptDragDropPayload("DOLLY_SECTION",ImGuiDragDropFlags_AcceptBeforeDelivery|ImGuiDragDropFlags_AcceptNoDrawDefaultRect)) {
        unsigned col=0;for(unsigned c=1;c<layout_columns_;++c)if(mouse.x>=origin.x+column_x_[c]-6*panel_scale)col=c;
        float y=card_origin_y_;
        for(unsigned i=0;i<section_count(lite_page_);++i)if(i!=source.index && section_columns_[i]==col)
            y=std::max(y,section_positions_[i].y+section_heights_[lite_page_][i]*panel_scale+section_extra_draw_[i]+12*panel_scale);
        const bool fits=y+size.y<=card_origin_y_+section_canvas_.y+1;
        const ImVec2 a(origin.x+column_x_[col],origin.y+y),b(a.x+column_widths_[col],a.y+size.y);
        GetWindowDrawList()->AddRect(a,b,fits ? GetColorU32(ImGuiCol_SliderGrab) : IM_COL32(190,125,100,180),5*panel_scale,0,2*panel_scale);
        if(accepted->IsDelivery() && fits) {
            for(unsigned i=0;i<section_count(lite_page_);++i)section_column_pref_[lite_page_][i]=int(section_columns_[i]);
            const auto old=section_slots_[lite_page_][source.index];
            for(unsigned i=0;i<section_count(lite_page_);++i)if(section_slots_[lite_page_][i]>old)--section_slots_[lite_page_][i];
            section_slots_[lite_page_][source.index]=section_count(lite_page_)-1;
            section_column_pref_[lite_page_][source.index]=int(col);
            sections_changed_at_[lite_page_]=GetTime();save_layout();
        }
    }
    EndDragDropTarget();
}
void OverlayPanel::layout_controls() {
    using namespace ImGui;
    if (Button("Layout")) OpenPopup("##layout-menu");
    if (BeginPopup("##layout-menu")) {
        TextUnformatted("Workspace layout");
        Separator();
        if (Checkbox("Arrange panels", &layout_editing_)) {
            if (layout_editing_) layout_custom_ = true;
            MarkIniSettingsDirty();
        }
        TextDisabled("Menu header always moves freely.\nArrange unlocks section placement and resize handles.");
        if (Button("Classic arrangement", ImVec2(-1, 0))) {
            classic_layout_ = true; layout_custom_ = false; editor_custom_ = false; editor_position_pending_ = false; layout_editing_ = false; layout_reset_ = 7; compact_paths_ = false;
            MarkIniSettingsDirty(); CloseCurrentPopup();
        }
        if (Button("Reset sections in this tab",ImVec2(-1,0))) {
            for(unsigned i=0;i<4;++i) {section_slots_[lite_page_][i]=i;section_column_pref_[lite_page_][i]=-1;section_minimum_[lite_page_][i]=0;}
            for(float& weight:column_weights_[lite_page_])weight=1;
            sections_changed_at_[lite_page_]=GetTime();save_layout();CloseCurrentPopup();
        }
        Separator();
        if (Checkbox("Reduce motion", &reduced_motion_)) MarkIniSettingsDirty();
        TextDisabled("Positions and sections save automatically.");
        EndPopup();
    }
}
} // namespace dolly

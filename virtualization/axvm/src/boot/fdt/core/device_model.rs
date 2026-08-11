//! Conventional FDT nodes derived from the resolved device graph.

use std::{
    collections::{BTreeMap, BTreeSet},
    format,
    string::{String, ToString},
    vec::Vec,
};

use axdevice::{
    DeviceFirmwareBinding, DeviceFirmwareProperty, DeviceFirmwareSpec, DeviceNodeId,
    DeviceNodeKind, ResolvedDeviceGraph, ResolvedDeviceResources, ResolvedWiredIrq,
};
use fdt_edit::{Fdt, Node, NodeId, Property};
use fdt_raw::RegInfo;

use super::tree::{FdtTree, prop_string};
use crate::{AxVmResult, ax_err_type};

const RESERVED_PROPERTIES: &[&str] = &[
    "compatible",
    "interrupt-parent",
    "interrupts",
    "reg",
    "status",
];

#[derive(Clone, Debug)]
struct ExistingNode {
    path: String,
    base_name: String,
    compatible: Vec<String>,
}

/// Adds conventional virtual-device nodes from one immutable resource plan.
///
/// Architecture-owned topology such as interrupt controllers and serial ports
/// remains in its specialized composer. Every other virtual node consumes the
/// exact firmware specification and resolved resources retained by the graph.
pub(crate) fn patch_resolved_devices<F>(
    fdt_bytes: &[u8],
    graph: &ResolvedDeviceGraph,
    specialized_node_ids: &[String],
    encode_interrupt: F,
) -> AxVmResult<Vec<u8>>
where
    F: Fn(ResolvedWiredIrq) -> AxVmResult<Vec<u32>>,
{
    let mut tree = FdtTree::from_bytes(fdt_bytes)?;
    let existing_nodes = snapshot_existing_nodes(tree.inner());
    let specialized_node_ids = specialized_node_ids
        .iter()
        .map(String::as_str)
        .collect::<BTreeSet<_>>();
    let mut firmware_paths = bound_fdt_paths(graph);

    for node in graph.nodes() {
        if node.kind() != DeviceNodeKind::Virtual
            || !matches!(node.firmware_binding(), DeviceFirmwareBinding::None)
            || specialized_node_ids.contains(node.id().as_str())
        {
            continue;
        }

        let firmware = node.firmware();
        if firmware.is_empty() {
            continue;
        }
        reject_predeclared_model_node(node.id(), &firmware, &existing_nodes)?;
        let resources = graph.resources_for(node.id())?;
        let path = install_device_node(
            &mut tree,
            node.id(),
            node.parent(),
            &firmware,
            resources,
            &firmware_paths,
            &encode_interrupt,
        )?;
        firmware_paths.insert(node.id().clone(), path);
    }

    let bytes = tree.finish();
    Fdt::from_bytes(&bytes).map_err(|error| {
        ax_err_type!(
            InvalidData,
            format!("invalid graph-derived guest FDT: {error:?}")
        )
    })?;
    Ok(bytes)
}

fn install_device_node<F>(
    tree: &mut FdtTree,
    node_id: &DeviceNodeId,
    parent: Option<&DeviceNodeId>,
    firmware: &DeviceFirmwareSpec,
    resources: &ResolvedDeviceResources,
    firmware_paths: &BTreeMap<DeviceNodeId, String>,
    encode_interrupt: &F,
) -> AxVmResult<String>
where
    F: Fn(ResolvedWiredIrq) -> AxVmResult<Vec<u32>>,
{
    let node_name = validate_node_name(node_id, firmware)?;
    validate_properties(node_id, firmware)?;
    let registers = resolve_registers(node_id, firmware, resources)?;
    let interrupts = resolve_interrupts(node_id, firmware, resources, encode_interrupt)?;
    let unit_name = registers.first().map_or_else(
        || node_name.to_string(),
        |register| format!("{node_name}@{:x}", register.address),
    );
    let (parent_id, parent_path) = resolve_parent(tree, node_id, parent, firmware_paths)?;
    let path = child_path(&parent_path, &unit_name);
    if tree.inner().get_by_path_id(&path).is_some() {
        return Err(ax_err_type!(
            InvalidData,
            format!(
                "resolved device '{}' collides with existing FDT node {path}",
                node_id.as_str()
            )
        ));
    }

    let fdt_node = tree.add_node(parent_id, Node::new(&unit_name));
    install_node_properties(tree, fdt_node, firmware, &registers, &interrupts)?;
    Ok(path)
}

fn validate_node_name<'a>(
    node_id: &DeviceNodeId,
    firmware: &'a DeviceFirmwareSpec,
) -> AxVmResult<&'a str> {
    let name = firmware
        .node_name()
        .map(String::as_str)
        .ok_or_else(|| firmware_error(node_id, "non-empty firmware metadata has no node name"))?;
    if name.is_empty()
        || name.contains(['/', '@'])
        || !name
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b',' | b'.' | b'_' | b'-'))
    {
        return Err(firmware_error(
            node_id,
            format!("'{name}' is not a valid conventional FDT node name"),
        ));
    }
    Ok(name)
}

fn validate_properties(node_id: &DeviceNodeId, firmware: &DeviceFirmwareSpec) -> AxVmResult {
    let mut names = BTreeSet::new();
    for property in firmware.properties() {
        let name = match property {
            DeviceFirmwareProperty::Flag { name }
            | DeviceFirmwareProperty::U32 { name, .. }
            | DeviceFirmwareProperty::String { name, .. } => name,
        };
        if RESERVED_PROPERTIES.contains(&name.as_str()) {
            return Err(firmware_error(
                node_id,
                format!("property '{name}' is owned by the FDT composer"),
            ));
        }
        if name.is_empty() || name.contains('/') || !names.insert(name.as_str()) {
            return Err(firmware_error(
                node_id,
                format!("property '{name}' is empty, duplicated, or contains '/'"),
            ));
        }
    }
    Ok(())
}

fn resolve_registers(
    node_id: &DeviceNodeId,
    firmware: &DeviceFirmwareSpec,
    resources: &ResolvedDeviceResources,
) -> AxVmResult<Vec<RegInfo>> {
    let mut seen = BTreeSet::new();
    firmware
        .register_slots()
        .iter()
        .map(|slot| {
            if !seen.insert(slot.as_str()) {
                return Err(firmware_error(
                    node_id,
                    format!("register slot '{slot}' is listed more than once"),
                ));
            }
            let (base, size) = resources.mmio(slot)?;
            Ok(RegInfo::new(base, Some(size)))
        })
        .collect()
}

fn resolve_interrupts<F>(
    node_id: &DeviceNodeId,
    firmware: &DeviceFirmwareSpec,
    resources: &ResolvedDeviceResources,
    encode_interrupt: &F,
) -> AxVmResult<Vec<u32>>
where
    F: Fn(ResolvedWiredIrq) -> AxVmResult<Vec<u32>>,
{
    let mut seen = BTreeSet::new();
    let mut cells = Vec::new();
    for slot in firmware.interrupt_slots() {
        if !seen.insert(slot.as_str()) {
            return Err(firmware_error(
                node_id,
                format!("interrupt slot '{slot}' is listed more than once"),
            ));
        }
        let encoded = encode_interrupt(resources.wired_irq(slot)?)?;
        if encoded.is_empty() {
            return Err(firmware_error(
                node_id,
                format!("interrupt slot '{slot}' produced an empty FDT specifier"),
            ));
        }
        cells.extend(encoded);
    }
    Ok(cells)
}

fn resolve_parent(
    tree: &mut FdtTree,
    node_id: &DeviceNodeId,
    parent: Option<&DeviceNodeId>,
    firmware_paths: &BTreeMap<DeviceNodeId, String>,
) -> AxVmResult<(NodeId, String)> {
    let Some(parent) = parent else {
        return Ok((tree.inner().root_id(), "/".to_string()));
    };
    let path = firmware_paths.get(parent).ok_or_else(|| {
        firmware_error(
            node_id,
            format!("firmware parent '{parent}' has no FDT path"),
        )
    })?;
    let parent_id = tree.inner().get_by_path_id(path).ok_or_else(|| {
        firmware_error(
            node_id,
            format!("firmware parent '{parent}' path '{path}' is absent"),
        )
    })?;
    Ok((parent_id, path.clone()))
}

fn install_node_properties(
    tree: &mut FdtTree,
    node: NodeId,
    firmware: &DeviceFirmwareSpec,
    registers: &[RegInfo],
    interrupts: &[u32],
) -> AxVmResult {
    if !firmware.compatible().is_empty() {
        let compatible = firmware
            .compatible()
            .iter()
            .map(String::as_str)
            .collect::<Vec<_>>();
        let mut property = Property::new("compatible", Vec::new());
        property.set_string_ls(&compatible);
        tree.set_property(node, property)?;
    }
    if !registers.is_empty() {
        tree.inner_mut()
            .view_typed_mut(node)
            .ok_or_else(|| ax_err_type!(InvalidData, "new graph FDT node is missing"))?
            .set_regs(registers);
    }
    if !interrupts.is_empty() {
        let parent = interrupt_parent_phandle(tree)?;
        tree.set_property(node, prop_u32("interrupt-parent", parent))?;
        tree.set_property(node, prop_u32_list("interrupts", interrupts))?;
    }
    for property in firmware.properties() {
        let property = match property {
            DeviceFirmwareProperty::Flag { name } => Property::new(name, Vec::new()),
            DeviceFirmwareProperty::U32 { name, value } => prop_u32(name, *value),
            DeviceFirmwareProperty::String { name, value } => prop_string(name, value),
        };
        tree.set_property(node, property)?;
    }
    tree.set_property(node, prop_string("status", "okay"))
}

fn interrupt_parent_phandle(tree: &mut FdtTree) -> AxVmResult<u32> {
    if let Some(parent) = tree
        .inner()
        .node(tree.inner().root_id())
        .and_then(|root| root.get_property("interrupt-parent"))
        .and_then(Property::get_u32)
    {
        if controller_with_phandle(tree.inner(), parent).is_some() {
            return Ok(parent);
        }
        return Err(ax_err_type!(
            InvalidData,
            format!("guest FDT root references missing interrupt parent {parent:#x}")
        ));
    }

    let controllers = tree
        .inner()
        .iter_node_ids()
        .filter(|id| {
            tree.inner()
                .node(*id)
                .is_some_and(|node| node.get_property("interrupt-controller").is_some())
        })
        .collect::<Vec<_>>();
    let [controller] = controllers.as_slice() else {
        return Err(ax_err_type!(
            InvalidData,
            format!(
                "guest FDT needs exactly one default interrupt controller, found {}",
                controllers.len()
            )
        ));
    };
    if let Some(phandle) = node_phandle(tree.inner(), *controller) {
        return Ok(phandle);
    }

    let phandle = next_phandle(tree.inner());
    tree.set_property(*controller, prop_u32("phandle", phandle))?;
    tree.set_property(*controller, prop_u32("linux,phandle", phandle))?;
    Ok(phandle)
}

fn snapshot_existing_nodes(fdt: &Fdt) -> Vec<ExistingNode> {
    fdt.iter_node_ids()
        .filter_map(|id| {
            let node = fdt.node(id)?;
            let name = node.name();
            Some(ExistingNode {
                path: fdt.path_of(id),
                base_name: name.split('@').next().unwrap_or(name).to_string(),
                compatible: node.compatibles().map(ToString::to_string).collect(),
            })
        })
        .collect()
}

fn reject_predeclared_model_node(
    node_id: &DeviceNodeId,
    firmware: &DeviceFirmwareSpec,
    existing_nodes: &[ExistingNode],
) -> AxVmResult {
    let Some(node_name) = firmware.node_name().map(String::as_str) else {
        return Ok(());
    };
    let duplicate = existing_nodes.iter().find(|node| {
        node.base_name == node_name
            && (firmware.compatible().is_empty()
                || node
                    .compatible
                    .iter()
                    .any(|value| firmware.compatible().contains(value)))
    });
    if let Some(duplicate) = duplicate {
        return Err(firmware_error(
            node_id,
            format!(
                "template node '{}' duplicates a graph-owned device model",
                duplicate.path
            ),
        ));
    }
    Ok(())
}

fn bound_fdt_paths(graph: &ResolvedDeviceGraph) -> BTreeMap<DeviceNodeId, String> {
    graph
        .nodes()
        .filter_map(|node| match node.firmware_binding() {
            DeviceFirmwareBinding::FdtNode(path) => Some((node.id().clone(), path.clone())),
            DeviceFirmwareBinding::AcpiDevice(_) | DeviceFirmwareBinding::None => None,
        })
        .collect()
}

fn child_path(parent: &str, child: &str) -> String {
    if parent == "/" {
        format!("/{child}")
    } else {
        format!("{parent}/{child}")
    }
}

fn controller_with_phandle(fdt: &Fdt, phandle: u32) -> Option<NodeId> {
    fdt.iter_node_ids().find(|id| {
        fdt.node(*id).is_some_and(|node| {
            node.get_property("interrupt-controller").is_some()
                && node_phandle(fdt, *id) == Some(phandle)
        })
    })
}

fn node_phandle(fdt: &Fdt, node: NodeId) -> Option<u32> {
    fdt.node(node)?
        .get_property("phandle")
        .or_else(|| fdt.node(node)?.get_property("linux,phandle"))
        .and_then(Property::get_u32)
}

fn next_phandle(fdt: &Fdt) -> u32 {
    fdt.iter_node_ids()
        .filter_map(|id| node_phandle(fdt, id))
        .max()
        .unwrap_or(0)
        .saturating_add(1)
        .max(1)
}

fn prop_u32(name: &str, value: u32) -> Property {
    prop_u32_list(name, &[value])
}

fn prop_u32_list(name: &str, values: &[u32]) -> Property {
    let mut property = Property::new(name, Vec::new());
    property.set_u32_ls(values);
    property
}

fn firmware_error(node_id: &DeviceNodeId, detail: impl Into<String>) -> crate::AxVmError {
    crate::AxVmError::invalid_config(format!(
        "device '{}' firmware metadata is invalid: {}",
        node_id.as_str(),
        detail.into()
    ))
}

#[cfg(test)]
mod tests {
    use std::sync::Arc;

    use axdevice::{
        DeviceBuildContext, DeviceBundle, DeviceGraphBuilder, DeviceManagerResult, DeviceModel,
        DeviceNodeSpec, DeviceRequirements, ResourcePools, ResourceRequest, ResourceSlot,
    };
    use axdevice_base::{
        ControllerInputId, InterruptControllerId, InterruptSharing, InterruptTrigger,
        InterruptTriggerMode,
    };

    use super::*;

    struct ConventionalDeviceModel;

    impl DeviceModel for ConventionalDeviceModel {
        fn requirements(&self) -> DeviceManagerResult<DeviceRequirements> {
            DeviceRequirements::new()
                .with_mmio(
                    ResourceSlot::new("registers")?,
                    0x1000,
                    0x1000,
                    ResourceRequest::Auto,
                )?
                .with_wired_irq(
                    ResourceSlot::new("irq")?,
                    InterruptControllerId::new(7),
                    InterruptTrigger::LevelTriggered,
                    InterruptSharing::Exclusive,
                    ResourceRequest::Auto,
                )
        }

        fn firmware(&self) -> DeviceFirmwareSpec {
            DeviceFirmwareSpec::new("virtio_mmio")
                .with_compatible("virtio,mmio")
                .with_register(ResourceSlot::new("registers").unwrap())
                .with_interrupt(ResourceSlot::new("irq").unwrap())
                .with_flag_property("dma-coherent")
                .with_u32_property("vendor,queue-count", 2)
                .with_string_property("vendor,mode", "split")
        }

        fn build(
            &self,
            _context: &mut DeviceBuildContext<'_>,
        ) -> DeviceManagerResult<DeviceBundle> {
            Ok(DeviceBundle::new())
        }
    }

    #[test]
    fn resolved_graph_populates_conventional_fdt_node() {
        let graph = resolved_graph();
        let source = source_fdt();
        let patched = patch_resolved_devices(&source, &graph, &[], |irq| {
            assert_eq!(irq.controller(), InterruptControllerId::new(7));
            let spi = irq.input().value().checked_sub(32).unwrap();
            let flags = match irq.trigger() {
                InterruptTriggerMode::EdgeTriggered => 1,
                InterruptTriggerMode::LevelTriggered => 4,
            };
            Ok(vec![0, u32::try_from(spi).unwrap(), flags])
        })
        .unwrap();

        let fdt = Fdt::from_bytes(&patched).unwrap();
        let device = fdt.get_by_path("/virtio_mmio@b000000").unwrap();
        assert_eq!(device.regs()[0].address, 0x0b00_0000);
        assert_eq!(device.regs()[0].size, Some(0x1000));
        assert_eq!(
            device.as_node().compatibles().collect::<Vec<_>>(),
            ["virtio,mmio"]
        );
        assert_eq!(
            device
                .as_node()
                .get_property("interrupts")
                .unwrap()
                .get_u32_iter()
                .collect::<Vec<_>>(),
            [0, 0, 4]
        );
        assert_eq!(
            device
                .as_node()
                .get_property("interrupt-parent")
                .and_then(Property::get_u32),
            Some(1)
        );
        assert_eq!(
            device
                .as_node()
                .get_property("vendor,queue-count")
                .and_then(Property::get_u32),
            Some(2)
        );
        assert_eq!(
            device
                .as_node()
                .get_property("vendor,mode")
                .and_then(Property::as_str),
            Some("split")
        );
        assert!(device.as_node().get_property("dma-coherent").is_some());
        assert_eq!(
            device
                .as_node()
                .get_property("status")
                .and_then(Property::as_str),
            Some("okay")
        );
    }

    #[test]
    fn runtime_template_rejects_predeclared_graph_device() {
        let graph = resolved_graph();
        let mut fdt = Fdt::from_bytes(&source_fdt()).unwrap();
        let root = fdt.root_id();
        let stale = fdt.add_node(root, Node::new("virtio_mmio@a000000"));
        fdt.node_mut(stale)
            .unwrap()
            .set_property(prop_string("compatible", "virtio,mmio"));
        let source = fdt.encode().as_ref().to_vec();

        let error =
            patch_resolved_devices(&source, &graph, &[], |_| Ok(vec![0, 0, 4])).unwrap_err();

        assert!(
            error
                .to_string()
                .contains("duplicates a graph-owned device model")
        );
    }

    fn resolved_graph() -> ResolvedDeviceGraph {
        let mut builder = DeviceGraphBuilder::new();
        builder
            .add(DeviceNodeSpec::virtual_device(
                DeviceNodeId::new("net0").unwrap(),
                Arc::new(ConventionalDeviceModel),
            ))
            .unwrap();
        let mut pools = ResourcePools::new();
        pools.add_auto_mmio(0x0b00_0000..0x0b01_0000).unwrap();
        pools
            .add_auto_controller_inputs(
                InterruptControllerId::new(7),
                ControllerInputId::new(32)..ControllerInputId::new(40),
            )
            .unwrap();
        builder.declare().unwrap().resolve(pools).unwrap()
    }

    fn source_fdt() -> Vec<u8> {
        let mut fdt = Fdt::new();
        let root = fdt.root_id();
        fdt.node_mut(root)
            .unwrap()
            .set_property(prop_u32("#address-cells", 2));
        fdt.node_mut(root)
            .unwrap()
            .set_property(prop_u32("#size-cells", 2));
        fdt.node_mut(root)
            .unwrap()
            .set_property(prop_u32("interrupt-parent", 1));
        let controller = fdt.add_node(root, Node::new("interrupt-controller@8000000"));
        fdt.node_mut(controller)
            .unwrap()
            .set_property(Property::new("interrupt-controller", Vec::new()));
        fdt.node_mut(controller)
            .unwrap()
            .set_property(prop_u32("#interrupt-cells", 3));
        fdt.node_mut(controller)
            .unwrap()
            .set_property(prop_u32("phandle", 1));
        fdt.encode().as_ref().to_vec()
    }
}

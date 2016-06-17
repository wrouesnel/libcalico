package libcalico

import (
	"github.com/docker/libkv"
	"github.com/wrouesnel/go.log"
	"net"
)

const (

)

type AllocationBlockHandleId string
type AllocationBlockAttributeIndex int64

type AllocationBlock struct {

}

// A block of IP addresses from which to allocate for IPAM clients.
//
// Blocks are identified by IP prefix.  Each block is a single, keyed object
// in etcd and the value of the block object in the datastore encodes all the
// allocations for all the IP addresses within that prefix.
//
// Thus, allocations and releases of IP addresses correspond to changes in the
// block's value.  Compare-and-swap atomicity is used to ensure allocations
// and releases are consistent operations.
//
// If another process updates the Block in the data store, then we will fail
// to write this one.  The owning code will need to
// - drop the invalid instance,
// - re-read a new instance from the data store,
// - recompute the required modifications, and
// - try the compare-and-swap operation again.
func NewAllocationBlock() *AllocationBlock {
	return &AllocationBlock{

	}
}

// Get the attribute indexes for a given handle.
// handle_id: The handle ID to search for.
// returns: List of attribute indexes.
func (this *AllocationBlock) getAddrIndexesByHandle(handleId AllocationBlockHandleId) []AllocationBlockAttributeIndex {

}

// Delete some attributes (used during release processing).
//
// This removes the attributes from the self.attributes list, and updates
// the allocation list with the new indexes.
//
// :param attr_indexes_to_delete: set of indexes of attributes to delete
// :param ordinals: list of ordinals of IPs to release (for debugging)
// :return: None.
func (this *AllocationBlock) deleteAttributes(attrIndexesToDelete []AllocationBlockAttributeIndex, ordinals []int64) {

}

// Walk the allocations and get a dictionary of reference counts to each
// set of attributes
func (this *AllocationBlock) getAttributeRefCounts() {

}

// Check if the key and attributes match existing and return the index, or
// if they don't exist, add them and return the index.
func (this *AllocationBlock) findOrAddAttrs() {

}

// Verify the integrity of attribute & allocations.
//
// This is a debug-only function to detect errors.
func (this *AllocationBlock) verifyAttributes() {

}

// Verify the integrity of the unallocated array.
//
// This is a debug-only function to detect errors.
func (this *AllocationBlock) verifyUnallocated() {

}

// Get the block ID to which a given address belongs.
// :param address: IPAddress
func GetBlockCIDRForAddress(address net.IP) {

}

// Check that the CIDR block size is valid.  This checks that it is at least
// as large as the minimum block size.
func ValidateBlockSize(cidr net.IPNet) {

}

type BlockError struct {
	LibCalicoError
}

type NoHostAffinityError struct {
	LibCalicoError
}

type AlreadyAssignedError struct {
	LibCalicoError
}

type AddressNotAssignedError struct {
	LibCalicoError
}